"""HTTP failures stay distinct from successful-response parsing and transport errors."""
import logging
from unittest.mock import Mock

import pytest
import requests

from infoblox_inventory.client import InfobloxClient, WapiError
from infoblox_inventory.config import GridConfig, load_config


SENSITIVE = "Authorization: Basic user:never-echo-password; https://user:never-echo-password@proxy.invalid"


def _client(status=200, *, version="2.13.7", body=SENSITIVE):
    session = requests.Session()
    response = Mock(status_code=status, text=body, content=body.encode())
    session.get = Mock(return_value=response)
    return InfobloxClient(GridConfig("LAB", "https://grid.example", version), "user", "never-echo-password", session), response


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503, 504])
def test_http_status_precedes_json_parsing_and_sensitive_body_is_omitted(status, caplog):
    client, response = _client(status)
    response.json.side_effect = AssertionError("HTTP errors must not be parsed as success JSON")
    with client, caplog.at_level(logging.DEBUG), pytest.raises(WapiError) as caught:
        client.get_all_objects("network")
    assert str(caught.value) == f"GET /network failed: HTTP {status}"
    assert caught.value.status_code == status
    response.json.assert_not_called()
    assert "never-echo-password" not in str(caught.value) + caplog.text
    assert "Authorization" not in str(caught.value) + caplog.text
    client.session.get.assert_called_once()
    assert client.session.get.call_args.args == ("https://grid.example/wapi/v2.13.7/network",)
    assert client.session.get.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503, 504])
def test_version_discovery_preserves_http_failure_status_without_duplicate_argument(status, caplog):
    client, response = _client(status)
    with client, caplog.at_level(logging.DEBUG), pytest.raises(WapiError) as caught:
        client.detect_version()
    assert caught.value.status_code == status
    assert str(caught.value).endswith(f"GET / failed: HTTP {status}")
    assert "multiple values" not in str(caught.value)
    assert "never-echo-password" not in str(caught.value) + caplog.text
    response.json.assert_not_called()
    assert client.session.get.call_count == 1


def test_malformed_success_json_keeps_http_status_and_suppresses_sensitive_body(caplog):
    client, response = _client(200)
    response.json.side_effect = ValueError(SENSITIVE)
    with client, caplog.at_level(logging.DEBUG), pytest.raises(WapiError) as caught:
        client.get("network")
    assert str(caught.value) == "GET /network returned invalid JSON"
    assert caught.value.status_code == 200
    assert caught.value.__suppress_context__ is True
    assert "never-echo-password" not in str(caught.value) + caplog.text
    response.json.assert_called_once_with()


@pytest.mark.parametrize("error_type", [requests.ConnectionError, requests.Timeout,
                                       requests.ReadTimeout, requests.ConnectTimeout])
def test_transport_and_timeout_errors_remain_distinguishable_and_sanitized(error_type, caplog):
    client, response = _client()
    client.session.get.side_effect = error_type(SENSITIVE)
    with client, caplog.at_level(logging.DEBUG), pytest.raises(WapiError) as caught:
        client.get("network")
    assert str(caught.value) == f"GET /network failed ({error_type.__name__})"
    assert caught.value.status_code is None
    assert caught.value.__suppress_context__ is True
    assert "never-echo-password" not in str(caught.value) + caplog.text
    assert "Authorization" not in str(caught.value) + caplog.text
    response.json.assert_not_called()


@pytest.mark.parametrize("configured_version", ["2.13.7", "v2.13.7"])
def test_configured_version_forms_use_exact_wapi_prefix_for_root_and_objects(tmp_path, configured_version):
    config_path = tmp_path / "grids.yaml"
    config_path.write_text("grids:\n  - name: LAB\n    url: https://grid.example/\n"
                           f"    wapi_version: {configured_version}\n", encoding="utf-8")
    grid, = load_config(config_path)
    assert grid.wapi_version == "2.13.7"
    session = requests.Session()
    root_response = Mock(status_code=200)
    root_response.json.return_value = {"supported_versions": ["2.13.7"], "requested_version": "2.13.7"}
    objects_response = Mock(status_code=200)
    objects_response.json.return_value = {"result": []}
    session.get = Mock(side_effect=[root_response, objects_response])
    with InfobloxClient(grid, "user", "never-echo-password", session) as client:
        assert client.detect_version() == "2.13.7"
        assert client.get_all_objects("network") == []
    assert [call.args[0] for call in session.get.call_args_list] == [
        "https://grid.example/wapi/v2.13.7/", "https://grid.example/wapi/v2.13.7/network"]
    assert all(call.kwargs["allow_redirects"] is False for call in session.get.call_args_list)

from copy import deepcopy
import logging
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
import responses

from infoblox_inventory.client import InfobloxClient, WapiError
from infoblox_inventory.config import GridConfig

BASE = "https://grid.example/wapi/v2.13.7"


def client(session=None, version="2.13.7"):
    return InfobloxClient(GridConfig("JB", "https://grid.example", version), "user", "secret", session)


def query(call):
    return parse_qs(urlsplit(call.request.url).query)


@responses.activate
def test_pagination_collects_every_page_and_uses_get_only():
    pages = [
        {"result": [{"_ref": "network/a", "unknown": {"keep": True}}], "next_page_id": "page-2"},
        {"result": [{"_ref": "network/b"}]},
    ]
    originals = deepcopy(pages)
    for page in pages:
        responses.add(responses.GET, BASE + "/network", json=page)
    persisted = []
    records = client().get_all_objects(
        "network", ["network", "comment"], {"_inheritance": True, "network_view": "default"},
        max_results=25, page_callback=lambda number, page: persisted.append((number, deepcopy(page))),
    )
    assert [record["_ref"] for record in records] == ["network/a", "network/b"]
    assert all(call.request.method == "GET" for call in responses.calls)
    assert query(responses.calls[0]) == {
        "_paging": ["1"], "_return_as_object": ["1"], "_max_results": ["25"],
        "_return_fields": ["network,comment"], "_inheritance": ["True"], "network_view": ["default"],
    }
    assert query(responses.calls[1]) == {"_page_id": ["page-2"]}
    assert persisted == list(enumerate(originals, start=1))
    assert records[0] == originals[0]["result"][0]


@responses.activate
def test_empty_paged_result_is_valid():
    responses.add(responses.GET, BASE + "/network", json={"result": []})
    assert client().get_all_objects("network") == []


@responses.activate
def test_empty_intermediate_page_does_not_end_collection():
    responses.add(responses.GET, BASE + "/network", json={"result": [], "next_page_id": "next"})
    responses.add(responses.GET, BASE + "/network", json={"result": [{"_ref": "network/a"}]})
    assert client().get_all_objects("network") == [{"_ref": "network/a"}]


@responses.activate
@pytest.mark.parametrize("page", [
    [], {"result": {}}, {"result": [None]}, {"result": ["record"]},
    {"Error": "secret"}, {}, {"result": [], "next_page_id": 123},
    {"result": [], "next_page_id": ""}, {"result": [], "next_page_id": None},
])
def test_malformed_page_is_preserved_then_rejected(page):
    responses.add(responses.GET, BASE + "/network", json=page)
    persisted = []
    with pytest.raises(WapiError) as error:
        client().get_all_objects("network", page_callback=lambda number, data: persisted.append((number, data)))
    assert persisted == [(1, page)]
    assert "secret" not in str(error.value)


@responses.activate
def test_pagination_rejects_non_adjacent_token_cycle():
    for token in ["page-a", "page-b", "page-a"]:
        responses.add(responses.GET, BASE + "/network", json={"result": [], "next_page_id": token})
    with pytest.raises(WapiError, match="Pagination loop"):
        client().get_all_objects("network")
    assert len(responses.calls) == 3


@responses.activate
def test_redirect_is_refused_without_forwarding_credentials():
    responses.add(responses.GET, BASE + "/networkview", status=302,
                  headers={"Location": "https://other.example/secret"})
    with pytest.raises(WapiError, match="Redirect refused") as error:
        client().get("networkview")
    assert len(responses.calls) == 1
    assert "secret" not in str(error.value)


@responses.activate
def test_http_error_never_exposes_server_text_and_is_not_retried():
    responses.add(responses.GET, BASE + "/network", body="Authorization: user:secret", status=403)
    with pytest.raises(WapiError) as error:
        client().get("network")
    assert str(error.value) == "GET /network failed: HTTP 403"
    assert error.value.status_code == 403
    assert len(responses.calls) == 1


@responses.activate
def test_rate_limited_get_status_is_retried(monkeypatch):
    monkeypatch.setattr("infoblox_inventory.client.sleep", lambda seconds: None)
    responses.add(responses.GET, BASE + "/network", status=429)
    responses.add(responses.GET, BASE + "/network", json=[])
    assert client().get("network") == []
    assert len(responses.calls) == 2
    assert all(call.request.method == "GET" for call in responses.calls)


@responses.activate
def test_service_unavailable_status_is_not_retried():
    responses.add(responses.GET, BASE + "/network", body="secret", status=503)
    with pytest.raises(WapiError, match="HTTP 503"):
        client().get("network")
    assert len(responses.calls) == 1


@responses.activate
def test_request_exception_is_sanitized(caplog):
    responses.add(responses.GET, BASE + "/network", body=requests.ConnectionError("user:secret"))
    with caplog.at_level(logging.DEBUG), pytest.raises(WapiError) as error:
        client().get("network")
    assert "secret" not in str(error.value)
    assert "secret" not in caplog.text
    assert error.value.__suppress_context__


@responses.activate
def test_invalid_json_error_does_not_chain_server_content():
    responses.add(responses.GET, BASE + "/network", body="secret not JSON")
    with pytest.raises(WapiError, match="invalid JSON") as error:
        client().get("network")
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__


@responses.activate
@pytest.mark.parametrize("response", [{"Error": "secret"}, {}, ["bad object"]])
def test_unpaged_get_rejects_non_object_lists(response):
    responses.add(responses.GET, BASE + "/network", json=response)
    with pytest.raises(WapiError) as error:
        client().get("network")
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("endpoint", [
    "https://other.example/network", "//other.example/network", "/network", "../network",
    "network/a", "network?_function=next_available_ip", "network%2fref", "request", "fileop",
])
def test_invalid_endpoint_is_rejected_before_request(endpoint):
    with pytest.raises(WapiError):
        client().get_all_objects(endpoint)


@pytest.mark.parametrize("control", [
    "_function", "_method", "_schema", "_page_id", "_paging",
    "_return_as_object", "_max_results", "_return_fields", "_return_fields+",
])
def test_filters_cannot_override_read_only_collection_controls(control):
    with pytest.raises(WapiError, match="control parameters"):
        client().get_all_objects("network", filters={control: "anything"})


@pytest.mark.parametrize("size", [0, -1, True, 1.5, "100"])
def test_page_size_must_be_positive_integer(size):
    with pytest.raises(WapiError, match="integer between 1 and 1000"):
        client().get_all_objects("network", max_results=size)


@responses.activate
def test_baseline_is_verified_from_root_and_never_upgraded():
    responses.add(responses.GET, BASE + "/", json={
        "requested_version": "2.13.7",
        "supported_versions": ["2.14", "2.9", "2.13.7", "2.1"],
        "supported_objects": ["network"],
    })
    api = client(version="auto")
    assert api.detect_version() == "2.13.7"
    assert api.schema()["supported_objects"] == ["network"]
    assert api.detect_version() == "2.13.7"
    assert len(responses.calls) == 1
    assert urlsplit(responses.calls[0].request.url).path == "/wapi/v2.13.7/"
    assert query(responses.calls[0]) == {"_schema": ["1"]}


@responses.activate
def test_advertised_versions_without_baseline_do_not_select_newer_version():
    responses.add(responses.GET, BASE + "/", json={"supported_versions": ["2.14", "2.13.6"]})
    with pytest.raises(WapiError, match="absent from supported_versions"):
        client(version="auto").detect_version()
    assert len(responses.calls) == 1


@responses.activate
def test_explicit_version_is_honored():
    responses.add(responses.GET, "https://grid.example/wapi/v2.13.6/", json={
        "supported_versions": ["2.14", "2.13.7", "2.13.6"],
    })
    assert client(version="2.13.6").detect_version() == "2.13.6"


@responses.activate
def test_explicit_fallback_can_be_used_if_baseline_unavailable():
    responses.add(responses.GET, BASE + "/", status=404)
    responses.add(responses.GET, "https://grid.example/wapi/v2.13.6/", json={"supported_versions": ["2.13.6"]})
    assert client(version="auto").detect_version(candidates=["2.13.6"]) == "2.13.6"


@responses.activate
def test_permission_failure_does_not_probe_other_versions_or_objects():
    responses.add(responses.GET, BASE + "/", status=403)
    with pytest.raises(WapiError, match="HTTP 403"):
        client(version="auto").detect_version(candidates=["2.13.6"])
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("versions", [None, [], "2.13.7", [None], ["bad"]])
def test_malformed_version_discovery_fails(versions):
    responses.add(responses.GET, BASE + "/", json={"supported_versions": versions})
    with pytest.raises(WapiError):
        client().detect_version()


@responses.activate
def test_schema_requests_v2_searchable_metadata_and_caches():
    responses.add(responses.GET, BASE + "/network", json={"fields": [{"name": "network"}]})
    api = client()
    assert api.schema("network") == api.schema("network")
    assert len(responses.calls) == 1
    assert query(responses.calls[0]) == {
        "_schema": ["1"], "_schema_version": ["2"], "_schema_searchable": ["1"],
    }


def test_session_context_closes_once_and_configures_safe_retries(monkeypatch):
    session = requests.Session()
    close = Mock()
    monkeypatch.setattr(session, "close", close)
    with client(session) as api:
        assert session.auth == ("user", "secret")
        assert session.verify is True
        assert session.get_adapter("https://").max_retries.allowed_methods == frozenset({"GET"})
        assert session.get_adapter("https://").max_retries.respect_retry_after_header is False
    api.close()
    close.assert_called_once()
    with pytest.raises(WapiError, match="closed"):
        api.get("network")


@responses.activate
def test_timeout_and_no_redirect_settings_reach_requests(monkeypatch):
    session = requests.Session()
    original = session.get
    seen = []

    def get(url, **kwargs):
        seen.append(kwargs)
        return original(url, **kwargs)

    monkeypatch.setattr(session, "get", get)
    responses.add(responses.GET, BASE + "/network", json=[])
    api = client(session)
    api.get("network")
    assert seen[0]["timeout"] == api.grid.timeout
    assert seen[0]["allow_redirects"] is False

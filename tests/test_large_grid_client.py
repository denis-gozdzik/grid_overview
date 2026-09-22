"""Offline regressions for deterministic collection of expensive WAPI queries."""

from copy import deepcopy
import json
import logging
from unittest.mock import Mock

import pytest
import requests
from urllib3.exceptions import ReadTimeoutError

from infoblox_inventory.client import InfobloxClient, WapiError
from infoblox_inventory.config import GridConfig


def response(data=None, *, status=200, body=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = (body if body is not None else json.dumps(data)).encode("utf-8")
    result._content_consumed = True  # Session.get() reads the body when stream=False.
    result.headers.update(headers or {})
    return result


@pytest.fixture
def delays(monkeypatch):
    recorded = []
    monkeypatch.setattr("infoblox_inventory.client.sleep", recorded.append)
    return recorded


@pytest.fixture
def make_client(monkeypatch):
    clients = []

    def create(*effects, **config):
        api = InfobloxClient(GridConfig("LAB", "https://grid.example", **config),
                             "private-user", "private-password")
        monkeypatch.setattr(api.session, "get", Mock(side_effect=effects))
        clients.append(api)
        return api

    yield create
    for api in clients:
        api.close()


def request_logs(caplog):
    return [record for record in caplog.records
            if record.name == "infoblox_inventory.client" and "attempt=" in record.getMessage()]


@pytest.mark.parametrize("method,data", [("get", []), ("get_all_objects", {"result": []})])
def test_default_page_size_is_used_for_both_public_get_methods(make_client, method, data):
    api = make_client(response(data))
    assert getattr(api, method)("network") == []
    assert api.session.get.call_args.kwargs["params"]["_max_results"] == 250


@pytest.mark.parametrize("method,data", [("get", []), ("get_all_objects", {"result": []})])
@pytest.mark.parametrize("configured,override,expected", [
    (137, None, 137), (137, 1, 1), (137, 1000, 1000),
])
def test_configured_page_size_and_explicit_overrides(make_client, method, data,
                                                     configured, override, expected):
    api = make_client(response(data), page_size=configured)
    assert getattr(api, method)("network", max_results=override) == []
    assert api.session.get.call_args.kwargs["params"]["_max_results"] == expected


@pytest.mark.parametrize("method", ["get", "get_all_objects"])
@pytest.mark.parametrize("invalid", [0, -1, 1001, True, 2.5, "250", float("inf")])
def test_invalid_explicit_page_size_fails_before_any_http_request(make_client, method, invalid):
    api = make_client()
    with pytest.raises(WapiError):
        getattr(api, method)("network", max_results=invalid)
    api.session.get.assert_not_called()


@pytest.mark.parametrize("config,expected", [({}, (10.0, 60.0)), ({"timeout": (2.5, 17)}, (2.5, 17))])
def test_connection_and_read_timeouts_propagate_to_every_attempt(make_client, delays, config, expected):
    api = make_client(requests.ConnectTimeout("private endpoint"), response([]), **config)
    assert api.get("network") == []
    assert api.session.get.call_count == 2
    assert all(call.kwargs["timeout"] == expected for call in api.session.get.call_args_list)
    assert all(call.kwargs["allow_redirects"] is False for call in api.session.get.call_args_list)
    assert delays == [1]


def test_connect_timeout_is_retried_only_once_with_fixed_delay(make_client, delays, caplog):
    api = make_client(requests.ConnectTimeout("private-password"), response([]))
    with caplog.at_level(logging.INFO):
        assert api.get("fixedaddress", filters={"_inheritance": True}) == []
    assert api.session.get.call_count == 2
    assert delays == [1]
    logs = request_logs(caplog)
    assert len(logs) == 2
    assert "ConnectTimeout" in logs[0].getMessage()
    assert "attempt=1" in logs[0].getMessage()
    assert "attempt=2" in logs[1].getMessage()
    assert all("mode=effective" in record.getMessage() for record in logs)
    assert "private-password" not in caplog.text


def test_429_retry_ignores_server_retry_after_delay(make_client, delays):
    api = make_client(response(status=429, body="private-password", headers={"Retry-After": "3600"}),
                      response([]))
    assert api.get("network") == []
    assert api.session.get.call_count == 2
    assert delays == [1]


@pytest.mark.parametrize("failures,status,kind", [
    ([requests.ConnectTimeout("sensitive"), requests.ConnectTimeout("sensitive")], None, "ConnectTimeout"),
    ([response(status=429), response(status=429)], 429, "HTTP 429"),
    ([requests.ConnectTimeout("sensitive"), response(status=429)], 429, "HTTP 429"),
    ([response(status=429), requests.ConnectTimeout("sensitive")], None, "ConnectTimeout"),
])
def test_retry_budget_is_shared_between_connection_and_rate_limit_failures(
        make_client, delays, failures, status, kind):
    api = make_client(*failures, response([]))
    with pytest.raises(WapiError, match=kind) as error:
        api.get_all_objects("fixedaddress", filters={"_inheritance": True})
    assert error.value.status_code == status
    assert api.session.get.call_count == 2
    assert delays == [1]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 502, 503, 504])
def test_http_failure_does_not_repeat_expensive_queries(make_client, delays, caplog, status):
    api = make_client(response(status=status, body="Authorization: private-password"), response([]))
    with caplog.at_level(logging.INFO), pytest.raises(WapiError) as error:
        api.get_all_objects("range", filters={"_inheritance": True})
    assert str(error.value) == f"GET /range failed: HTTP {status}"
    assert error.value.status_code == status
    assert api.session.get.call_count == 1
    assert delays == []
    logs = request_logs(caplog)
    assert len(logs) == 1
    assert logs[0].levelno == logging.ERROR
    assert f"http_status={status}" in logs[0].getMessage()
    assert "mode=effective" in logs[0].getMessage()
    assert "private-password" not in caplog.text


@pytest.mark.parametrize("failure", [
    requests.ReadTimeout("private-password"),
    requests.ConnectionError("private-password"),
    requests.Timeout("private-password"),
    requests.exceptions.SSLError("private-password"),
    requests.exceptions.ChunkedEncodingError("private-password"),
])
def test_non_connect_request_failure_is_not_retried(make_client, delays, caplog, failure):
    api = make_client(failure, response([]))
    with caplog.at_level(logging.INFO), pytest.raises(WapiError) as error:
        api.get_all_objects("network", filters={"_inheritance": True})
    assert type(failure).__name__ in str(error.value)
    assert error.value.status_code is None
    assert error.value.__suppress_context__
    assert api.session.get.call_count == 1
    assert delays == []
    logs = request_logs(caplog)
    assert len(logs) == 1
    assert logs[0].levelno == logging.ERROR
    assert type(failure).__name__ in logs[0].getMessage()
    assert "private-password" not in caplog.text


def test_body_read_timeout_wrapped_by_requests_is_identified_without_retry(make_client, delays, caplog):
    wrapped = requests.ConnectionError(ReadTimeoutError(
        None, "https://private-user:private-password@grid.example/?_page_id=private-token",
        "Read timed out while receiving private data"))
    api = make_client(wrapped, response([]))
    with caplog.at_level(logging.INFO), pytest.raises(WapiError, match="ReadTimeout") as error:
        api.get_all_objects("range", filters={"_inheritance": True})
    assert api.session.get.call_count == 1
    assert delays == []
    assert error.value.status_code is None
    assert error.value.__suppress_context__
    logs = request_logs(caplog)
    assert len(logs) == 1
    assert logs[0].levelno == logging.ERROR
    assert "ReadTimeout" in logs[0].getMessage()
    for secret in ["private-user", "private-password", "private-token", "private data", "https://"]:
        assert secret not in caplog.text
        assert secret not in str(error.value)


def test_malformed_json_after_success_has_http_status_and_is_not_retried(make_client, delays, caplog):
    api = make_client(response(body="private-password is not JSON"), response([]))
    with caplog.at_level(logging.INFO), pytest.raises(WapiError, match="invalid JSON") as error:
        api.get_all_objects("fixedaddress")
    assert error.value.status_code == 200
    assert error.value.__suppress_context__
    assert api.session.get.call_count == 1
    assert delays == []
    logs = request_logs(caplog)
    assert len(logs) == 1
    assert logs[0].levelno == logging.ERROR
    assert "http_status=200" in logs[0].getMessage()
    assert "private-password" not in caplog.text


def test_urllib3_adapter_has_no_independent_retry_budget(make_client):
    api = make_client()
    for protocol in ("http://", "https://"):
        retry = api.session.get_adapter(protocol).max_retries
        assert retry.total == 0
        assert not retry.connect
        assert not retry.read
        assert not retry.status
        assert retry.backoff_factor == 0
        assert retry.respect_retry_after_header is False
        assert retry.allowed_methods == frozenset({"GET"})


@pytest.mark.parametrize("inheritance,mode", [(None, "raw"), (False, "raw"), (True, "effective"),
                                               ("True", "effective")])
def test_page_telemetry_retains_mode_and_size_when_continuation_has_only_token(
        make_client, caplog, monkeypatch, inheritance, mode):
    pages = [
        {"result": [{"_ref": "network/one"}], "next_page_id": "private-continuation-token"},
        {"result": [{"_ref": "network/two"}, {"_ref": "network/three"}]},
    ]
    originals = deepcopy(pages)
    api = make_client(*(response(page) for page in pages), page_size=125)
    persisted = []
    times = iter([10.0, 11.25, 20.0, 22.5])
    monkeypatch.setattr("infoblox_inventory.client.monotonic", lambda: next(times))
    filters = {} if inheritance is None else {"_inheritance": inheritance}
    with caplog.at_level(logging.INFO):
        records = api.get_all_objects("network", filters=filters,
                                      page_callback=lambda number, data: persisted.append((number, data)))
    assert len(records) == 3
    assert persisted == list(enumerate(originals, 1))
    assert pages == originals
    calls = api.session.get.call_args_list
    assert calls[0].kwargs["params"]["_max_results"] == 125
    expected_continuation = {"_page_id": "private-continuation-token"}
    if mode == "effective":
        expected_continuation["_inheritance"] = True
    assert calls[1].kwargs["params"] == expected_continuation
    logs = request_logs(caplog)
    assert len(logs) == 2
    for number, (record, count, elapsed) in enumerate(zip(logs, [1, 2], [1.25, 2.5]), 1):
        message = record.getMessage()
        assert record.levelno == logging.INFO
        for token in ["grid=LAB", "object_type=network", f"mode={mode}", f"page={number}",
                      "page_size=125", "attempt=1", f"result_count={count}", "http_status=200",
                      "outcome="]:
            assert token in message
        elapsed_token = next(token for token in message.split() if token.startswith("elapsed_seconds="))
        assert float(elapsed_token.split("=", 1)[1]) == elapsed
    assert "private-continuation-token" not in caplog.text
    assert "https://" not in caplog.text


def test_later_page_failure_logs_context_without_sensitive_queries_or_tokens(make_client, caplog):
    first_page = {"result": [{"_ref": "network/one"}], "next_page_id": "private-page-token"}
    api = make_client(response(first_page), requests.ReadTimeout(
        "https://private-user:private-password@grid.example/?_page_id=private-page-token&name=private-name"),
        page_size=83)
    persisted = []
    with caplog.at_level(logging.DEBUG), pytest.raises(WapiError) as error:
        api.get_all_objects("network", filters={"_inheritance": True, "name": "private-name"},
                            page_callback=lambda number, data: persisted.append((number, data)))
    assert persisted == [(1, first_page)]
    assert api.session.get.call_count == 2
    assert "ReadTimeout" in str(error.value)
    failed = request_logs(caplog)[-1]
    assert failed.levelno == logging.ERROR
    for token in ["grid=LAB", "object_type=network", "mode=effective", "page=2", "page_size=83",
                  "attempt=1", "ReadTimeout", "elapsed_seconds=", "result_count=", "http_status="]:
        assert token in failed.getMessage()
    for secret in ["private-user", "private-password", "private-name", "private-page-token", "https://"]:
        assert secret not in caplog.text
        assert secret not in str(error.value)


def test_schema_and_unpaged_collection_requests_have_distinct_log_modes(make_client, caplog):
    api = make_client(response({"fields": []}), response([{"_ref": "network/one"}]), page_size=123)
    with caplog.at_level(logging.INFO):
        api.schema("network")
        api.schema("network")  # The cached schema must not look like another request.
        api.get("network")
    logs = request_logs(caplog)
    assert len(logs) == 2
    assert "mode=schema" in logs[0].getMessage()
    assert "mode=raw" in logs[1].getMessage()
    assert "page_size=123" in logs[1].getMessage()
    assert "result_count=1" in logs[1].getMessage()
    assert all("http_status=200" in record.getMessage() for record in logs)


@pytest.mark.parametrize("method,data,kwargs,mode", [
    ("schema", [], {}, "schema"),
    ("get", {"unexpected": "private-data"}, {}, "raw"),
    ("get_all_objects", {"result": ["private-data"]}, {"filters": {"_inheritance": True}}, "effective"),
])
def test_invalid_response_shape_after_retry_preserves_status_and_actual_attempt(
        make_client, delays, caplog, method, data, kwargs, mode):
    api = make_client(response(status=429), response(data))
    with caplog.at_level(logging.INFO), pytest.raises(WapiError) as error:
        getattr(api, method)("network", **kwargs)
    assert api.session.get.call_count == 2
    assert delays == [1]
    assert error.value.status_code == 200
    failures = [record for record in request_logs(caplog) if "ProtocolError" in record.getMessage()]
    assert len(failures) == 1
    assert failures[0].levelno == logging.ERROR
    for token in ["object_type=network", f"mode={mode}", "attempt=2", "http_status=200", "outcome=error"]:
        assert token in failures[0].getMessage()
    assert "private-data" not in caplog.text
    assert "private-data" not in str(error.value)

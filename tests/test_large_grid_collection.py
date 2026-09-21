"""Large-Grid failure handling over mocked GETs and existing runtime schemas.

All pages generated here are synthetic transport scenarios. No LAB access or
existing fixture changes are needed to exercise pagination and offline replay.
"""
from copy import deepcopy
import json
from pathlib import Path
import socket
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
import responses

from infoblox_inventory.client import InfobloxClient
from infoblox_inventory.collectors.core import collect_grid
from infoblox_inventory.config import GridConfig
from infoblox_inventory.storage import load_raw, path_component


BASE = "https://grid.example/wapi/v2.13.7"
FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA_QUERY = {"_schema": "1", "_schema_version": "2", "_schema_searchable": "1"}


def add_schemas(object_types):
    responses.add(responses.GET, BASE + "/", json={
        "supported_objects": list(object_types), "supported_versions": ["2.13.7"],
    }, match=[responses.matchers.query_param_matcher({"_schema": "1"})])
    for object_type in object_types:
        family = ("live_lab_20260920/schema" if object_type in {"network", "range"}
                  else "topology_lab_20260920/schemas" if object_type == "dhcpoptionspace"
                  else "reservations_lab_20260920/schemas")
        path = FIXTURES / family / f"{path_component(object_type)}.json"
        responses.add(responses.GET, BASE + "/" + object_type,
                      json=json.loads(path.read_text(encoding="utf-8")),
                      match=[responses.matchers.query_param_matcher(SCHEMA_QUERY)])


def connection(**settings):
    return InfobloxClient(GridConfig("TEST-GRID", "https://grid.example", **settings),
                          "test-reader", "test-password")


def coverage_status(result, object_type, mode="raw"):
    return next(row["Collection Status"] for row in result.coverage
                if row.get("Object") == object_type and row.get("Query") == mode)


def read_manifest(tmp_path):
    return json.loads((tmp_path / "TEST-GRID" / "manifest.json").read_text(encoding="utf-8"))


def assert_offline_replay(tmp_path, result, monkeypatch):
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}

    def forbidden(*args, **kwargs):
        pytest.fail("Offline replay attempted network access")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    replay = load_raw(tmp_path)[0]
    assert replay.records == result.records
    assert replay.effective_records == result.effective_records
    assert replay.schemas == result.schemas
    assert replay.coverage == result.coverage
    assert replay.errors == result.errors
    assert all(path.read_bytes() == content for path, content in before.items())


@responses.activate
@pytest.mark.parametrize("object_type", ["network", "dhcpoptionspace", "fixedaddress", "superhostchild"])
@pytest.mark.parametrize("page_size", [None, 125])
def test_page_size_reaches_raw_effective_topology_and_parent_queries(tmp_path, object_type, page_size):
    objects = ["superhost", "superhostchild"] if object_type == "superhostchild" else [object_type]
    add_schemas(objects)
    saved = {}
    initial_queries = []

    def serve(request):
        parsed = urlsplit(request.url)
        current = parsed.path.rsplit("/", 1)[-1]
        params = parse_qs(parsed.query)
        if "_page_id" in params:
            mode, parent, number = params["_page_id"][0].split("|")
            page_number = int(number)
        else:
            mode = "effective" if params.get("_inheritance") == ["True"] else "raw"
            parent = params.get("parent", [""])[0]
            page_number = 1
            initial_queries.append((current, mode, parent, params))
        if current == "superhost":
            page = {"result": [{"_ref": f"superhost/parent-{page_number}",
                                "name": f"parent-{page_number}"}]}
        else:
            page = {"result": [{"_ref": f"{current}/{mode}/{parent}/{page_number}",
                                "unknown": {"preserve": [None, False, page_number]}}]}
        if page_number == 1:
            page["next_page_id"] = f"{mode}|{parent}|2"
        saved.setdefault((current, mode), []).append(deepcopy(page))
        return 200, {"Content-Type": "application/json"}, json.dumps(page)

    for current in objects:
        responses.add_callback(responses.GET, BASE + "/" + current, callback=serve)
    settings = {} if page_size is None else {"page_size": page_size}
    with connection(**settings) as client:
        result = collect_grid(client, str(tmp_path), object_type)

    assert not result.errors
    expected_size = 250 if page_size is None else page_size
    expected_modes = {"raw", "effective"} if object_type in {"network", "fixedaddress"} else {"raw"}
    assert {mode for current, mode, _parent, _params in initial_queries if current == object_type} == expected_modes
    for current, _mode, parent, params in initial_queries:
        assert params["_max_results"] == [str(expected_size)]
        assert params["_paging"] == params["_return_as_object"] == ["1"]
        if current == "superhostchild":
            assert parent in {"parent-1", "parent-2"}
            assert params["type"] == ["FixedAddress"]
    manifest = read_manifest(tmp_path)
    assert manifest["format_version"] == 1 and manifest["collection_finished"] is True
    for query in manifest["queries"]:
        assert query["params"]["_max_results"] == expected_size
        assert query["status"] == "COMPLETE"
        expected_pages = saved[(query["object_type"], query["mode"])]
        actual_pages = [json.loads((tmp_path / "TEST-GRID" / path).read_text(encoding="utf-8"))
                        for path in query["pages"]]
        assert actual_pages == expected_pages
        if query["object_type"] == "superhostchild":
            assert len(query["pages"]) == 4  # Two pages per parent, no archive path collisions.
            assert [subquery["params"]["parent"] for subquery in query["subqueries"]] == ["parent-1", "parent-2"]
            assert all(subquery["params"]["_max_results"] == expected_size for subquery in query["subqueries"])
    assert all(call.request.method == "GET" for call in responses.calls)


@responses.activate
@pytest.mark.parametrize("mode", ["raw", "effective"])
@pytest.mark.parametrize("completed_pages,populated", [(0, False), (2, False), (2, True)])
@pytest.mark.parametrize("failure", ["ReadTimeout", "HTTP504"])
def test_core_timeout_preserves_pages_and_continues_other_queries_and_objects(
        tmp_path, monkeypatch, mode, completed_pages, populated, failure):
    add_schemas(["network", "range"])
    successful = []
    failed_calls = []

    def serve(request):
        parsed = urlsplit(request.url)
        object_type = parsed.path.rsplit("/", 1)[-1]
        params = parse_qs(parsed.query)
        if "_page_id" in params:
            current_mode, number = params["_page_id"][0].split(":")
            page_number = int(number)
        else:
            current_mode = "effective" if params.get("_inheritance") == ["True"] else "raw"
            page_number = 1
        if object_type == "network" and current_mode == mode:
            if page_number > completed_pages:
                failed_calls.append((object_type, current_mode, page_number))
                if failure == "ReadTimeout":
                    raise requests.exceptions.ReadTimeout("sensitive transport text must not be stored")
                return 504, {}, "gateway timeout"
            page = {"result": [{"_ref": f"network/{mode}/{page_number}",
                                "unknown": {"preserve": [False, None, page_number]}}] if populated else [],
                    "next_page_id": f"{mode}:{page_number + 1}"}
            successful.append(deepcopy(page))
        else:
            page = {"result": [{"_ref": f"{object_type}/{current_mode}/success"}]}
        return 200, {"Content-Type": "application/json"}, json.dumps(page)

    for object_type in ["network", "range"]:
        responses.add_callback(responses.GET, BASE + "/" + object_type, callback=serve)
    with connection(page_size=150) as client:
        result = collect_grid(client, str(tmp_path), "options")

    expected_status = "PARTIAL" if completed_pages else "ERROR"
    assert coverage_status(result, "network", mode) == expected_status
    assert len(result.errors) == 1
    assert result.errors[0]["object_type"] == "network" and result.errors[0]["query"] == mode
    assert ("ReadTimeout" if failure == "ReadTimeout" else "HTTP 504") in result.errors[0]["error"]
    assert "sensitive transport text" not in result.errors[0]["error"]
    assert failed_calls == [("network", mode, completed_pages + 1)]
    target = result.records if mode == "raw" else result.effective_records
    assert target["network"] == [row for page in successful for row in page["result"]]
    other = result.effective_records if mode == "raw" else result.records
    assert len(other["network"]) == 1
    assert len(result.records["range"]) == len(result.effective_records["range"]) == 1
    manifest = read_manifest(tmp_path)
    failed_query = next(query for query in manifest["queries"]
                        if query["object_type"] == "network" and query["mode"] == mode)
    assert failed_query["status"] == expected_status
    assert len(failed_query["pages"]) == completed_pages
    assert failed_query["record_count"] == (completed_pages if populated else 0)
    assert [json.loads((tmp_path / "TEST-GRID" / page).read_text(encoding="utf-8"))
            for page in failed_query["pages"]] == successful
    assert_offline_replay(tmp_path, result, monkeypatch)


@responses.activate
@pytest.mark.parametrize("scenario", ["first_page", "later_page_empty", "later_page_populated", "second_parent_after_empty"])
def test_child_timeout_tracks_successful_pages_per_parent_and_preserves_scope(tmp_path, monkeypatch, scenario):
    add_schemas(["superhost", "superhostchild"])
    parents = [{"_ref": "superhost/one", "name": "one"}]
    if scenario == "second_parent_after_empty":
        parents.append({"_ref": "superhost/two", "name": "two"})
    responses.add(responses.GET, BASE + "/superhost", json={"result": parents})
    first_pages = []
    if scenario != "first_page":
        first = {"result": [{"_ref": "superhostchild/one", "parent": "one", "type": "FixedAddress"}]
                             if scenario == "later_page_populated" else []}
        if scenario != "second_parent_after_empty":
            first["next_page_id"] = "next-child-page"
        first_pages.append(first)
        responses.add(responses.GET, BASE + "/superhostchild", json=first)
    responses.add(responses.GET, BASE + "/superhostchild", body=requests.exceptions.ReadTimeout("private"))
    with connection(page_size=175) as client:
        result = collect_grid(client, str(tmp_path), "superhostchild")

    expected = "ERROR" if scenario == "first_page" else "PARTIAL"
    assert coverage_status(result, "superhostchild") == expected
    assert len(result.errors) == 1 and "ReadTimeout" in result.errors[0]["error"]
    assert result.records["superhostchild"] == [row for page in first_pages for row in page["result"]]
    query = next(query for query in read_manifest(tmp_path)["queries"] if query["object_type"] == "superhostchild")
    assert query["status"] == expected and len(query["pages"]) == len(first_pages)
    expected_substatuses = (["EMPTY", "ERROR"] if scenario == "second_parent_after_empty" else [expected])
    assert [subquery["status"] for subquery in query["subqueries"]] == expected_substatuses
    child_data = [parse_qs(urlsplit(call.request.url).query) for call in responses.calls
                  if urlsplit(call.request.url).path.endswith("/superhostchild")
                  and "_schema" not in parse_qs(urlsplit(call.request.url).query)]
    assert len(child_data) == (1 if scenario == "first_page" else 2)
    for params in child_data:
        if "_page_id" not in params:
            assert params["type"] == ["FixedAddress"]
            assert params["parent"][0] in {parent["name"] for parent in parents}
            assert params["_max_results"] == ["175"]
    assert_offline_replay(tmp_path, result, monkeypatch)


@responses.activate
def test_child_failure_continues_next_parent_and_later_collector(tmp_path, monkeypatch):
    add_schemas(["superhost", "superhostchild", "filtermac"])
    responses.add(responses.GET, BASE + "/superhost", json={"result": [
        {"_ref": "superhost/one", "name": "one"}, {"_ref": "superhost/two", "name": "two"},
    ]})
    responses.add(responses.GET, BASE + "/superhostchild", body=requests.exceptions.ReadTimeout("private"))
    pages = [
        {"result": [{"_ref": "superhostchild/two-a", "parent": "two", "type": "FixedAddress"}],
         "next_page_id": "parent-two-page-two"},
        {"result": [{"_ref": "superhostchild/two-b", "parent": "two", "type": "FixedAddress"}]},
    ]
    for page in pages:
        responses.add(responses.GET, BASE + "/superhostchild", json=page)
    responses.add(responses.GET, BASE + "/filtermac", json={"result": [{"_ref": "filtermac/one", "name": "one"}]})
    with connection(page_size=175) as client:
        result = collect_grid(client, str(tmp_path), "reservations_filters")

    assert len(result.errors) == 1 and result.errors[0]["parent"] == "one"
    assert coverage_status(result, "superhostchild") == "PARTIAL"
    assert coverage_status(result, "filtermac") == "COMPLETE"
    assert len(result.records["filtermac"]) == 1
    assert result.records["superhostchild"] == [row for page in pages for row in page["result"]]
    query = next(query for query in read_manifest(tmp_path)["queries"] if query["object_type"] == "superhostchild")
    assert query["status"] == "PARTIAL" and query["record_count"] == 2
    assert [subquery["status"] for subquery in query["subqueries"]] == ["ERROR", "COMPLETE"]
    assert [json.loads((tmp_path / "TEST-GRID" / page).read_text(encoding="utf-8")) for page in query["pages"]] == pages
    assert_offline_replay(tmp_path, result, monkeypatch)


@responses.activate
@pytest.mark.parametrize("limitation", ["missing_fields", "incomplete_parent"])
@pytest.mark.parametrize("empty_page_first", [False, True])
def test_child_failure_status_is_not_hidden_by_schema_or_parent_limitations(
        tmp_path, monkeypatch, limitation, empty_page_first):
    add_schemas(["superhost", "superhostchild"])
    if limitation == "missing_fields":
        schema_path = FIXTURES / "reservations_lab_20260920/schemas/superhostchild.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["fields"] = [field for field in schema["fields"] if field["name"] != "comment"]
        responses.replace(responses.GET, BASE + "/superhostchild", json=schema,
                          match=[responses.matchers.query_param_matcher(SCHEMA_QUERY)])
    parent_page = {"result": [{"_ref": "superhost/one", "name": "one"}]}
    if limitation == "incomplete_parent":
        parent_page["next_page_id"] = "parent-page-two"
    responses.add(responses.GET, BASE + "/superhost", json=parent_page)
    if limitation == "incomplete_parent":
        responses.add(responses.GET, BASE + "/superhost", status=504)
    if empty_page_first:
        responses.add(responses.GET, BASE + "/superhostchild",
                      json={"result": [], "next_page_id": "child-page-two"})
    responses.add(responses.GET, BASE + "/superhostchild", body=requests.exceptions.ReadTimeout("private"))
    with connection(page_size=175) as client:
        result = collect_grid(client, str(tmp_path), "superhostchild")

    expected = "PARTIAL" if empty_page_first else "ERROR"
    assert coverage_status(result, "superhostchild") == expected
    child_errors = [error for error in result.errors if error["object_type"] == "superhostchild"]
    assert len(child_errors) == 1 and "ReadTimeout" in child_errors[0]["error"]
    assert result.records["superhostchild"] == []
    if limitation == "incomplete_parent":
        assert coverage_status(result, "superhost") == "PARTIAL"
    else:
        assert any(row.get("Object") == "superhostchild" and row.get("Field") == "comment"
                   and row["Collection Status"] == "NOT_EXPOSED_BY_WAPI" for row in result.coverage)
    query = next(query for query in read_manifest(tmp_path)["queries"] if query["object_type"] == "superhostchild")
    assert query["status"] == query["subqueries"][0]["status"] == expected
    assert len(query["pages"]) == (1 if empty_page_first else 0)
    assert query["record_count"] == 0
    assert_offline_replay(tmp_path, result, monkeypatch)


@responses.activate
@pytest.mark.parametrize("empty_page_first", [False, True])
@pytest.mark.parametrize("object_type", ["dhcpoptionspace", "superhostchild"])
def test_malformed_pages_are_saved_but_do_not_count_as_success(tmp_path, monkeypatch, empty_page_first, object_type):
    objects = ["superhost", "superhostchild"] if object_type == "superhostchild" else [object_type]
    add_schemas(objects)
    if object_type == "superhostchild":
        responses.add(responses.GET, BASE + "/superhost", json={"result": [{"name": "one"}]})
    if empty_page_first:
        responses.add(responses.GET, BASE + "/" + object_type,
                      json={"result": [], "next_page_id": "bad-page"})
    malformed = {"result": "invalid", "opaque": {"preserve": [None, False]}}
    responses.add(responses.GET, BASE + "/" + object_type, json=malformed)
    with connection() as client:
        result = collect_grid(client, str(tmp_path), object_type)
    expected = "PARTIAL" if empty_page_first else "ERROR"
    assert result.records[object_type] == []
    assert coverage_status(result, object_type) == expected
    query = next(query for query in read_manifest(tmp_path)["queries"] if query["object_type"] == object_type)
    assert query["status"] == expected
    assert len(query["pages"]) == (2 if empty_page_first else 1)
    assert json.loads((tmp_path / "TEST-GRID" / query["pages"][-1]).read_text(encoding="utf-8")) == malformed
    assert_offline_replay(tmp_path, result, monkeypatch)

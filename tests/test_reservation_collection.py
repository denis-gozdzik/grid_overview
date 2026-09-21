"""Reservations/filter collection uses captured WAPI 2.13.7 schemas.

Empty/error responses below exercise transport and coverage; they do not claim
that the corresponding LAB objects are empty. Populated fixture provenance is
declared by the fixture helpers and tests that use it.
"""
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
import responses

from infoblox_inventory.client import InfobloxClient
from infoblox_inventory.collectors.core import collect_grid
from infoblox_inventory.collectors.reservations import RESERVATION_FILTERS, RESERVATION_OBJECTS
from infoblox_inventory.config import GridConfig
from infoblox_inventory.storage import load_raw, path_component


BASE = "https://grid.example/wapi/v2.13.7"
FIXTURES = Path(__file__).parent / "fixtures" / "reservations_lab_20260920"
OBJECT_TYPES = (
    "fixedaddress", "record:host", "record:host_ipv4addr", "roaminghost",
    "superhost", "superhostchild", "filtermac", "macfilteraddress", "filteroption",
    "filterrelayagent", "filterfingerprint", "filternac",
)
# Collection proved these eleven LAB endpoints empty. No standalone child
# response is fabricated: superhostchild requires a parent, and LAB parents
# are empty. Synthetic child dependency scenarios are explicitly labeled below.
LAB_EMPTY_TYPES = tuple(name for name in OBJECT_TYPES if name != "superhostchild")
SCHEMA_QUERY = {"_schema": "1", "_schema_version": "2", "_schema_searchable": "1"}


def lab_schema(object_type):
    return json.loads((FIXTURES / "schemas" / f"{path_component(object_type)}.json").read_text(encoding="utf-8"))


def empty_lab_page(object_type, mode="raw"):
    assert object_type in LAB_EMPTY_TYPES
    path = FIXTURES / "responses" / path_component(object_type) / mode / "page-000001.json"
    page = json.loads(path.read_text(encoding="utf-8"))
    assert page["result"] == []
    return page


def add_root(objects):
    responses.add(responses.GET, BASE + "/", json={
        "supported_objects": list(objects), "supported_versions": ["2.13.7"],
    }, match=[responses.matchers.query_param_matcher({"_schema": "1"})])


def add_schema(object_type, schema=None):
    responses.add(responses.GET, BASE + "/" + object_type,
                  json=lab_schema(object_type) if schema is None else schema,
                  match=[responses.matchers.query_param_matcher(SCHEMA_QUERY)])


def client():
    return InfobloxClient(GridConfig("LAB-GRID", "https://grid.example"), "readonly", "test-only")


def coverage(result, object_type, mode="raw"):
    return next(row for row in result.coverage
                if row.get("Object") == object_type and row.get("Query") == mode)


def data_calls():
    return [call for call in responses.calls
            if "_schema" not in parse_qs(urlsplit(call.request.url).query)]


def assert_get_only_scope():
    for call in responses.calls:
        parsed = urlsplit(call.request.url)
        assert call.request.method == "GET"
        assert parsed.path in {"/wapi/v2.13.7/", *(
            "/wapi/v2.13.7/" + object_type for object_type in OBJECT_TYPES)}
        query = parse_qs(parsed.query)
        assert not set(query) & {"_function", "_method", "_body", "_args"}
        if "_inheritance" in query:
            assert parsed.path == "/wapi/v2.13.7/fixedaddress"
            assert query["_inheritance"] == ["True"]


@responses.activate
@pytest.mark.parametrize("object_type", LAB_EMPTY_TYPES)
def test_reservation_requests_use_only_readable_runtime_fields(object_type):
    schema = lab_schema(object_type)
    add_root(OBJECT_TYPES)
    add_schema(object_type, schema)
    responses.add(responses.GET, BASE + "/" + object_type, json={"result": []})
    with client() as connection:
        result = collect_grid(connection, only=object_type)

    assert not result.errors
    assert result.records == {object_type: []}
    assert coverage(result, object_type)["Collection Status"] == "EMPTY"
    metadata = {field["name"]: field for field in schema["fields"]}
    assessment_fields = set(RESERVATION_OBJECTS[object_type][2])
    declared_flags = {metadata[name]["overridden_by"] for name in assessment_fields
                      if "overridden_by" in metadata[name]}
    calls = data_calls()
    assert len(calls) == (2 if object_type == "fixedaddress" else 1)
    for call in calls:
        query = parse_qs(urlsplit(call.request.url).query)
        requested = set(query["_return_fields"][0].split(","))
        assert requested == assessment_fields | declared_flags
        assert all("r" in metadata[name]["supports"] for name in requested)
        assert query["_paging"] == query["_return_as_object"] == ["1"]
        assert query["_max_results"] == ["250"]
        assert not requested & {"dns_associated_objects", "configure_for_dns", "aliases",
                                "zone", "view", "ttl", "ipv6addrs", "network_template",
                                "template", "failover_association", "member"}
        assert not any("password" in name or "secret" in name for name in requested)
        if object_type.startswith("filter") or object_type == "macfilteraddress":
            assert "extattrs" not in requested
            assert not any("ddns" in name for name in requested)
    if object_type == "fixedaddress":
        assert result.effective_records == {object_type: []}
        assert coverage(result, object_type, "effective")["Collection Status"] == "EMPTY"
        assert "_inheritance" not in parse_qs(urlsplit(calls[0].request.url).query)
        assert parse_qs(urlsplit(calls[1].request.url).query)["_inheritance"] == ["True"]
    else:
        assert not result.effective_records
    assert_get_only_scope()


@responses.activate
def test_reservations_filters_alias_exact_scope_empty_coverage_and_manifest(tmp_path):
    add_root([*OBJECT_TYPES, "record:a", "record:ptr", "ipv6fixedaddress", "extensibleattributedef"])
    for object_type in OBJECT_TYPES:
        add_schema(object_type)
        responses.add(responses.GET, BASE + "/" + object_type, json={"result": []})
    with client() as connection:
        result = collect_grid(connection, str(tmp_path), "reservations_filters")
    assert result.records == {object_type: [] for object_type in OBJECT_TYPES}
    assert not result.errors
    assert result.effective_records == {"fixedaddress": []}
    assert len(responses.calls) == 25  # root + 12 schemas + 11 RAW + fixedaddress effective
    assert_get_only_scope()
    for object_type in OBJECT_TYPES:
        assert coverage(result, object_type)["Collection Status"] == "EMPTY"
        assert coverage(result, object_type)["Objects Found"] == 0
    manifest = json.loads((tmp_path / "LAB-GRID" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["queries"]) == 13
    assert all(query["status"] == "EMPTY" for query in manifest["queries"])
    assert {(query["object_type"], query["mode"]) for query in manifest["queries"]} == {
        *((object_type, "raw") for object_type in OBJECT_TYPES), ("fixedaddress", "effective")}
    child_query = next(query for query in manifest["queries"] if query["object_type"] == "superhostchild")
    assert child_query["pages"] == child_query["subqueries"] == []
    assert child_query["parent_count"] == 0
    assert not (tmp_path / "LAB-GRID" / "superhostchild" / "raw").exists()


@responses.activate
def test_superhostchild_search_is_parent_scoped_and_preserves_per_parent_pages(tmp_path, monkeypatch):
    # Explicitly synthetic dependency scenario: complete LAB parent inventory
    # was empty, so no populated parent/child evidence can be captured there.
    empty_lab_page("superhost")
    object_type = "superhostchild"
    metadata = next(field for field in lab_schema(object_type)["fields"] if field["name"] == "type")
    assert "s" in metadata["supports"] and "=" in metadata["searchable_by"]
    assert "FixedAddress" in metadata["enum_values"]
    assert RESERVATION_FILTERS == {object_type: {"type": "FixedAddress"}}
    parents = [{"_ref": "superhost/synthetic-one", "name": "synthetic-one"},
               {"_ref": "superhost/synthetic-two", "name": "synthetic-two"}]
    pages = [
        {"result": [{"_ref": "superhostchild/synthetic-one", "parent": "synthetic-one",
                     "type": "FixedAddress", "data": "192.0.2.10",
                     "unknown_extension": {"keep": [None, False]}}],
         "next_page_id": "scope-preserved-in-opaque-token"},
        {"result": [{"_ref": "superhostchild/synthetic-two", "parent": "synthetic-one",
                     "type": "FixedAddress", "data": "192.0.2.11"}]},
        {"result": [{"_ref": "superhostchild/synthetic-three", "parent": "synthetic-two",
                     "type": "FixedAddress", "data": "192.0.2.12"}]},
    ]
    add_root(["superhost", object_type])
    add_schema("superhost")
    responses.add(responses.GET, BASE + "/superhost", json={"result": parents})
    add_schema(object_type)
    for page in pages:
        responses.add(responses.GET, BASE + "/" + object_type, json=page)
    with client() as connection:
        result = collect_grid(connection, str(tmp_path), object_type)
    assert not result.errors
    assert result.records["superhost"] == parents
    assert result.records[object_type] == [record for page in pages for record in page["result"]]
    assert coverage(result, object_type)["Collection Status"] == "COMPLETE"
    calls = [call for call in data_calls() if urlsplit(call.request.url).path.endswith("/superhostchild")]
    for call, parent in ((calls[0], "synthetic-one"), (calls[2], "synthetic-two")):
        query = parse_qs(urlsplit(call.request.url).query)
        assert query["type"] == ["FixedAddress"]
        assert query["parent"] == [parent]
        assert query["_paging"] == query["_return_as_object"] == ["1"]
        assert set(query["_return_fields"][0].split(",")) == set(RESERVATION_OBJECTS[object_type][2])
    assert parse_qs(urlsplit(calls[1].request.url).query) == {
        "_page_id": ["scope-preserved-in-opaque-token"]}
    manifest = json.loads((tmp_path / "LAB-GRID" / "manifest.json").read_text(encoding="utf-8"))
    child_query = next(query for query in manifest["queries"] if query["object_type"] == object_type)
    assert child_query["parent_object"] == "superhost"
    assert child_query["parent_count"] == 2
    assert len(child_query["subqueries"]) == 2
    assert [query["params"]["parent"] for query in child_query["subqueries"]] == ["synthetic-one", "synthetic-two"]
    assert [query["record_count"] for query in child_query["subqueries"]] == [2, 1]
    for index, page in enumerate(pages, 1):
        path = tmp_path / "LAB-GRID" / object_type / "raw" / f"page-{index:06d}.json"
        assert json.loads(path.read_text(encoding="utf-8")) == page
    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("Offline child replay used network"))
    replay = load_raw(tmp_path)[0]
    assert replay.records == result.records and replay.coverage == result.coverage
    assert_get_only_scope()


@responses.activate
def test_missing_reservation_filter_objects_do_not_trigger_guessed_queries():
    add_root([])
    with client() as connection:
        result = collect_grid(connection, only="reservations_filters")
    assert not result.records and not result.effective_records and not result.errors
    assert len(responses.calls) == 1
    for object_type in OBJECT_TYPES:
        assert any(row.get("Object") == object_type and row["Collection Status"] == "NOT_EXPOSED_BY_WAPI"
                   for row in result.coverage)


@responses.activate
def test_fixedaddress_missing_fields_and_changed_override_metadata_are_respected():
    object_type = "fixedaddress"
    schema = lab_schema(object_type)
    # An explicitly synthetic schema variation, with no populated object fixture.
    schema["fields"] = [field for field in schema["fields"] if field["name"] != "comment"]
    for field in schema["fields"]:
        if field["name"] == "bootfile":
            field["supports"] = "wu"
        if field["name"] == "nextserver":
            field["overridden_by"] = "synthetic_override_flag"
    schema["fields"].append({"name": "synthetic_override_flag", "supports": "rwu", "type": ["bool"]})
    add_root([object_type])
    add_schema(object_type, schema)
    responses.add(responses.GET, BASE + "/" + object_type, json={"result": []})
    with client() as connection:
        result = collect_grid(connection, only=object_type)
    assert not result.errors
    for call in data_calls():
        fields = set(parse_qs(urlsplit(call.request.url).query)["_return_fields"][0].split(","))
        assert "synthetic_override_flag" in fields
        assert not fields & {"comment", "bootfile", "use_nextserver"}
    assert coverage(result, object_type)["Collection Status"] == "PARTIAL"
    assert coverage(result, object_type, "effective")["Collection Status"] == "PARTIAL"
    missing = {row.get("Field") for row in result.coverage if row["Collection Status"] == "NOT_EXPOSED_BY_WAPI"}
    assert missing == {"comment", "bootfile", "template"}
    assert_get_only_scope()


@responses.activate
@pytest.mark.parametrize("schema_failure", ["forbidden", "malformed"])
def test_filter_schema_failure_never_falls_back_to_guessed_fields(schema_failure):
    add_root(["filterfingerprint"])
    if schema_failure == "forbidden":
        responses.add(responses.GET, BASE + "/filterfingerprint", status=403)
    else:
        responses.add(responses.GET, BASE + "/filterfingerprint", json={"fields": "invalid"})
    with client() as connection:
        result = collect_grid(connection, only="filterfingerprint")
    assert not result.records
    assert result.errors[0]["object_type"] == "filterfingerprint"
    assert any(row["Collection Status"] == "ERROR" for row in result.coverage)
    assert not any(row["Collection Status"] == "NOT_EXPOSED_BY_WAPI" for row in result.coverage)
    assert len(responses.calls) == 2
    assert not data_calls()


@responses.activate
@pytest.mark.parametrize("scope_field,scope_failure", [
    ("type", "absent"), ("type", "unsearchable"), ("type", "unsupported_value"),
    ("parent", "absent"), ("parent", "unsearchable"),
])
def test_missing_superhostchild_scope_capability_never_broadens_collection(scope_field, scope_failure):
    object_type = "superhostchild"
    schema = lab_schema(object_type)
    if scope_failure == "absent":
        schema["fields"] = [field for field in schema["fields"] if field["name"] != scope_field]
    else:
        metadata = next(field for field in schema["fields"] if field["name"] == scope_field)
        if scope_failure == "unsearchable":
            metadata["searchable_by"] = ""
        else:
            metadata["enum_values"] = ["ARecord"]
    add_root(["superhost", object_type])
    add_schema("superhost")
    responses.add(responses.GET, BASE + "/superhost", json={"result": []})
    add_schema(object_type, schema)
    with client() as connection:
        result = collect_grid(connection, only=object_type)
    assert not result.records.get(object_type) and not result.errors
    assert coverage(result, object_type)["Collection Status"] == "PARTIAL"
    assert len(responses.calls) == 4
    assert all(urlsplit(call.request.url).path.endswith("/superhost") for call in data_calls())


@responses.activate
@pytest.mark.parametrize("parent_problem", ["invalid_name", "partial_page", "schema_error", "not_exposed"])
def test_child_inventory_cannot_be_empty_when_parent_discovery_is_incomplete(tmp_path, parent_problem):
    # Synthetic dependency scenarios are permitted by complete, empty LAB parents.
    empty_lab_page("superhost")
    add_root(["superhostchild"] if parent_problem == "not_exposed" else ["superhost", "superhostchild"])
    if parent_problem != "not_exposed":
        if parent_problem == "schema_error":
            responses.add(responses.GET, BASE + "/superhost", status=403)
        else:
            add_schema("superhost")
            parents = [{"_ref": "superhost/synthetic-valid", "name": "synthetic-valid"}]
            if parent_problem == "invalid_name":
                parents.append({"_ref": "superhost/synthetic-invalid", "name": None})
            parent_page = {"result": parents}
            if parent_problem == "partial_page":
                parent_page["next_page_id"] = "unavailable-parent-page"
            responses.add(responses.GET, BASE + "/superhost", json=parent_page)
            if parent_problem == "partial_page":
                responses.add(responses.GET, BASE + "/superhost", status=403)
    add_schema("superhostchild")
    if parent_problem in {"invalid_name", "partial_page"}:
        responses.add(responses.GET, BASE + "/superhostchild", json={"result": []})
    with client() as connection:
        result = collect_grid(connection, str(tmp_path), "superhostchild")
    assert coverage(result, "superhostchild")["Collection Status"] == "PARTIAL"
    child_calls = [call for call in data_calls() if urlsplit(call.request.url).path.endswith("/superhostchild")]
    assert len(child_calls) == (1 if parent_problem in {"invalid_name", "partial_page"} else 0)
    for call in child_calls:
        query = parse_qs(urlsplit(call.request.url).query)
        assert query["parent"] == ["synthetic-valid"]
        assert query["type"] == ["FixedAddress"]
    replay = load_raw(tmp_path)[0]
    assert replay.records == result.records and replay.coverage == result.coverage
    assert_get_only_scope()


@responses.activate
@pytest.mark.parametrize("failure_position", ["first_only", "second_parent", "second_page"])
def test_child_query_failures_retain_scoped_evidence_and_never_report_empty(tmp_path, failure_position):
    empty_lab_page("superhost")
    add_root(["superhost", "superhostchild"])
    add_schema("superhost")
    parents = [{"_ref": "superhost/synthetic-one", "name": "synthetic-one"}]
    if failure_position == "second_parent":
        parents.append({"_ref": "superhost/synthetic-two", "name": "synthetic-two"})
    responses.add(responses.GET, BASE + "/superhost", json={"result": parents})
    add_schema("superhostchild")
    if failure_position != "first_only":
        child_page = {"result": [{"_ref": "superhostchild/synthetic", "parent": "synthetic-one",
                                  "type": "FixedAddress", "data": "192.0.2.10"}]}
        if failure_position == "second_page":
            child_page["next_page_id"] = "unavailable-child-page"
        responses.add(responses.GET, BASE + "/superhostchild", json=child_page)
    responses.add(responses.GET, BASE + "/superhostchild", status=403)
    with client() as connection:
        result = collect_grid(connection, str(tmp_path), "superhostchild")
    expected_status = "ERROR" if failure_position == "first_only" else "PARTIAL"
    assert coverage(result, "superhostchild")["Collection Status"] == expected_status
    assert len(result.records["superhostchild"]) == (0 if failure_position == "first_only" else 1)
    assert any(error["object_type"] == "superhostchild" and "403" in error["error"] for error in result.errors)
    manifest = json.loads((tmp_path / "LAB-GRID" / "manifest.json").read_text(encoding="utf-8"))
    child_query = next(query for query in manifest["queries"] if query["object_type"] == "superhostchild")
    assert child_query["status"] == expected_status
    assert len(child_query["pages"]) == (0 if failure_position == "first_only" else 1)
    replay = load_raw(tmp_path)[0]
    assert replay.records == result.records and replay.coverage == result.coverage
    assert replay.errors == result.errors
    assert_get_only_scope()


@responses.activate
@pytest.mark.parametrize("object_type", LAB_EMPTY_TYPES)
def test_synthetic_pages_for_empty_lab_types_preserve_nested_raw_offline(tmp_path, monkeypatch, object_type):
    empty_lab_page(object_type)  # Persisted live evidence permits synthetic populated data.
    schema = lab_schema(object_type)
    add_root(OBJECT_TYPES)
    add_schema(object_type, schema)
    first_row = {"_ref": f"{object_type}/synthetic-1",
                 "unknown_extension": {"value": [None, False, 1.25, "Zażółć"]}}
    second_row = {"_ref": f"{object_type}/synthetic-2"}
    if any(field["name"] == "name" for field in schema["fields"]):
        first_row["name"] = "synthetic-one"
        second_row["name"] = "synthetic-two"
    pages = [
        {"result": [first_row], "next_page_id": "opaque:page/2", "unknown_envelope": {"keep": True}},
        {"result": [second_row], "unknown_envelope": [None, "keep"]},
    ]
    expected_pages = deepcopy(pages)
    for page in pages:
        responses.add(responses.GET, BASE + "/" + object_type, json=page)
    if object_type == "fixedaddress":
        responses.add(responses.GET, BASE + "/" + object_type,
                      json=empty_lab_page(object_type, "effective"))
    with client() as connection:
        result = collect_grid(connection, str(tmp_path), object_type)
    assert not result.errors
    assert result.records == {object_type: [first_row, second_row]}
    assert result.effective_records == ({"fixedaddress": []} if object_type == "fixedaddress" else {})
    assert coverage(result, object_type)["Collection Status"] == "COMPLETE"
    assert coverage(result, object_type)["Objects Found"] == 2
    assert len(responses.calls) == (5 if object_type == "fixedaddress" else 4)
    assert_get_only_scope()
    calls = data_calls()
    assert "_inheritance" not in parse_qs(urlsplit(calls[0].request.url).query)
    assert parse_qs(urlsplit(calls[1].request.url).query) == {"_page_id": ["opaque:page/2"]}
    archive = tmp_path / "LAB-GRID"
    for number, expected in enumerate(expected_pages, 1):
        path = archive / path_component(object_type) / "raw" / f"page-{number:06d}.json"
        assert json.loads(path.read_text(encoding="utf-8")) == expected
    saved_schema = archive / "schema" / f"{path_component(object_type)}.json"
    assert json.loads(saved_schema.read_text(encoding="utf-8")) == schema

    def forbidden(*args, **kwargs):
        pytest.fail("Offline reservation/filter replay attempted network access")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    before = {path: path.read_bytes() for path in archive.rglob("*.json")}
    replay = load_raw(tmp_path)[0]
    assert replay.records == result.records
    assert replay.effective_records == result.effective_records
    assert replay.schemas == result.schemas
    assert replay.coverage == result.coverage
    assert replay.errors == result.errors
    assert all(path.read_bytes() == content for path, content in before.items())


@responses.activate
def test_filter_second_page_failure_preserves_partial_raw_and_coverage(tmp_path):
    object_type = "filtermac"
    empty_lab_page(object_type)
    add_root([object_type])
    add_schema(object_type)
    # Synthetic populated page for an endpoint whose real LAB result was empty.
    first = {"result": [{"_ref": "filtermac/synthetic", "name": "Corporate",
                         "unknown_extension": {"keep": [None, False]}}], "next_page_id": "later"}
    responses.add(responses.GET, BASE + "/" + object_type, json=first)
    responses.add(responses.GET, BASE + "/" + object_type, status=403)
    with client() as connection:
        result = collect_grid(connection, str(tmp_path), object_type)
    assert result.records[object_type] == first["result"]
    assert coverage(result, object_type)["Collection Status"] == "PARTIAL"
    assert coverage(result, object_type)["Objects Found"] == 1
    assert result.errors[0]["query"] == "raw"
    assert "403" in result.errors[0]["error"]
    replay = load_raw(tmp_path)[0]
    assert replay.records == result.records
    assert replay.coverage == result.coverage
    assert replay.errors == result.errors
    assert_get_only_scope()

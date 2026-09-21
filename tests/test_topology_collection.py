"""Topology collection against real LAB schemas and explicitly synthetic pages.

The schemas were captured from WAPI 2.13.7. Every populated response below is
synthetic: these tests neither claim populated LAB objects nor access the LAB.
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
from infoblox_inventory.collectors.topology import TOPOLOGY_OBJECTS
from infoblox_inventory.config import GridConfig
from infoblox_inventory.storage import load_raw


BASE = "https://grid.example/wapi/v2.13.7"
SCHEMAS = Path(__file__).parent / "fixtures" / "topology_lab_20260920" / "schemas"
OBJECT_TYPES = (
    "dhcpfailover", "networktemplate", "rangetemplate", "fixedaddresstemplate",
    "dhcpoptionspace", "dhcpoptiondefinition",
)
SCHEMA_QUERY = {"_schema": "1", "_schema_version": "2", "_schema_searchable": "1"}


def lab_schema(object_type):
    return json.loads((SCHEMAS / f"{object_type}.json").read_text(encoding="utf-8"))


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


def raw_coverage(result, object_type):
    return next(row for row in result.coverage
                if row.get("Object") == object_type and row.get("Query") == "raw")


def assert_get_only_topology():
    for call in responses.calls:
        parsed = urlsplit(call.request.url)
        assert call.request.method == "GET"
        assert parsed.path in {"/wapi/v2.13.7/", *(
            "/wapi/v2.13.7/" + object_type for object_type in OBJECT_TYPES)}
        query = parse_qs(parsed.query)
        assert "_inheritance" not in query
        assert "_function" not in query


@responses.activate
@pytest.mark.parametrize("object_type", OBJECT_TYPES)
def test_topology_pages_use_live_schema_fields_and_preserve_raw_offline(tmp_path, monkeypatch, object_type):
    schema = lab_schema(object_type)
    add_root(OBJECT_TYPES)
    add_schema(object_type, schema)
    # Synthetic opaque data deliberately exercises information outside typed fields.
    first_row = {"_ref": f"{object_type}/synthetic-1", "name": "synthetic-one",
                 "unknown_extension": {"value": [None, False, 1.25, "Zażółć"]}}
    second_row = {"_ref": f"{object_type}/synthetic-2", "name": "synthetic-two"}
    pages = [
        {"result": [first_row], "next_page_id": "opaque:page/2", "unknown_envelope": {"keep": True}},
        {"result": [second_row], "unknown_envelope": [None, "keep"]},
    ]
    expected_pages = deepcopy(pages)
    for page in pages:
        responses.add(responses.GET, BASE + "/" + object_type, json=page)

    with client() as connection:
        result = collect_grid(connection, str(tmp_path), object_type)

    assert not result.errors
    assert result.records == {object_type: [first_row, second_row]}
    assert not result.effective_records
    assert raw_coverage(result, object_type)["Collection Status"] == "COMPLETE"
    assert raw_coverage(result, object_type)["Objects Found"] == 2
    assert len(responses.calls) == 4
    assert_get_only_topology()
    first_query = parse_qs(urlsplit(responses.calls[2].request.url).query)
    assert first_query["_paging"] == first_query["_return_as_object"] == ["1"]
    assert first_query["_max_results"] == ["250"]
    requested = set(first_query["_return_fields"][0].split(","))
    metadata = {field["name"]: field for field in schema["fields"]}
    assessment_fields = set(TOPOLOGY_OBJECTS[object_type][2])
    declared_flags = {metadata[name]["overridden_by"] for name in assessment_fields
                      if "overridden_by" in metadata[name]}
    assert requested == assessment_fields | declared_flags
    assert all("r" in metadata[name]["supports"] for name in requested)
    assert not requested & {"extattrs", "ms_shared_secret", "set_dhcp_failover_partner_down",
                            "set_dhcp_failover_secondary_recovery"}
    assert not any("ddns" in name or "filter" in name for name in requested)
    assert parse_qs(urlsplit(responses.calls[3].request.url).query)["_page_id"] == ["opaque:page/2"]
    archive = tmp_path / "LAB-GRID"
    for number, expected in enumerate(expected_pages, 1):
        path = archive / object_type / "raw" / f"page-{number:06d}.json"
        assert json.loads(path.read_text(encoding="utf-8")) == expected
    assert json.loads((archive / "schema" / f"{object_type}.json").read_text(encoding="utf-8")) == schema

    def forbidden(*args, **kwargs):
        pytest.fail("Offline topology replay attempted network access")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    before = {path: path.read_bytes() for path in archive.rglob("*.json")}
    replay = load_raw(tmp_path)[0]
    assert replay.records == result.records
    assert replay.schemas == result.schemas
    assert replay.coverage == result.coverage
    assert replay.errors == result.errors
    assert not replay.effective_records
    assert all(path.read_bytes() == content for path, content in before.items())


@responses.activate
def test_topology_alias_collects_exactly_six_objects_and_reports_empty_results(tmp_path):
    add_root([*OBJECT_TYPES, "fixedaddress", "filtermac", "filteroption", "record:a", "extensibleattributedef"])
    for object_type in OBJECT_TYPES:
        add_schema(object_type)
        responses.add(responses.GET, BASE + "/" + object_type, json={"result": []})
    with client() as connection:
        result = collect_grid(connection, str(tmp_path), "topology")
    assert result.records == {object_type: [] for object_type in OBJECT_TYPES}
    assert not result.errors
    assert not result.effective_records
    assert len(responses.calls) == 13
    assert_get_only_topology()
    for object_type in OBJECT_TYPES:
        assert raw_coverage(result, object_type)["Collection Status"] == "EMPTY"
        assert raw_coverage(result, object_type)["Objects Found"] == 0
    manifest = json.loads((tmp_path / "LAB-GRID" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["queries"]) == 6
    assert all(query["status"] == "EMPTY" and query["mode"] == "raw" for query in manifest["queries"])


@responses.activate
def test_missing_topology_object_is_coverage_without_data_or_schema_requests():
    add_root([])
    with client() as connection:
        result = collect_grid(connection, only="topology")
    assert not result.records
    assert not result.errors
    assert len(responses.calls) == 1
    for object_type in OBJECT_TYPES:
        assert any(row.get("Object") == object_type and row["Collection Status"] == "NOT_EXPOSED_BY_WAPI"
                   for row in result.coverage)


@responses.activate
def test_template_missing_fields_and_runtime_override_metadata_are_respected():
    object_type = "networktemplate"
    schema = lab_schema(object_type)
    # Synthetic schema variation: demonstrate selection follows runtime metadata.
    schema["fields"] = [field for field in schema["fields"] if field["name"] != "comment"]
    for field in schema["fields"]:
        if field["name"] == "bootfile":
            field["supports"] = "wu"
        if field["name"] == "nextserver":
            field["overridden_by"] = "synthetic_override_flag"
    schema["fields"].append({"name": "synthetic_override_flag", "supports": "rwu", "type": ["bool"]})
    add_root([object_type])
    add_schema(object_type, schema)
    responses.add(responses.GET, BASE + "/" + object_type,
                  json={"result": [{"_ref": "networktemplate/synthetic", "name": "synthetic"}]})
    with client() as connection:
        result = collect_grid(connection, only=object_type)
    assert not result.errors
    query = parse_qs(urlsplit(responses.calls[2].request.url).query)
    fields = set(query["_return_fields"][0].split(","))
    assert "synthetic_override_flag" in fields
    assert not fields & {"comment", "bootfile", "use_nextserver"}
    assert raw_coverage(result, object_type)["Collection Status"] == "PARTIAL"
    missing = {row.get("Field") for row in result.coverage if row["Collection Status"] == "NOT_EXPOSED_BY_WAPI"}
    assert missing == {"comment", "bootfile"}
    assert len(responses.calls) == 3
    assert_get_only_topology()


@responses.activate
@pytest.mark.parametrize("schema_failure", ["forbidden", "malformed"])
def test_topology_schema_failure_never_falls_back_to_guessed_fields(schema_failure):
    add_root(["dhcpoptionspace"])
    if schema_failure == "forbidden":
        responses.add(responses.GET, BASE + "/dhcpoptionspace", status=403)
    else:
        responses.add(responses.GET, BASE + "/dhcpoptionspace", json={"fields": "invalid"})
    with client() as connection:
        result = collect_grid(connection, only="dhcpoptionspace")
    assert not result.records
    assert result.errors[0]["object_type"] == "dhcpoptionspace"
    assert any(row["Collection Status"] == "ERROR" for row in result.coverage)
    assert not any(row["Collection Status"] == "NOT_EXPOSED_BY_WAPI" for row in result.coverage)
    assert len(responses.calls) == 2
    assert all("_return_fields" not in parse_qs(urlsplit(call.request.url).query) for call in responses.calls)


@responses.activate
def test_topology_partial_second_page_preserves_replayable_evidence(tmp_path):
    object_type = "rangetemplate"
    add_root([object_type])
    add_schema(object_type)
    first = {"result": [{"_ref": "rangetemplate/synthetic", "name": "synthetic",
                         "unknown_extension": {"keep": [None, False]}}], "next_page_id": "later"}
    responses.add(responses.GET, BASE + "/" + object_type, json=first)
    responses.add(responses.GET, BASE + "/" + object_type, status=403)
    with client() as connection:
        result = collect_grid(connection, str(tmp_path), object_type)
    assert result.records[object_type] == first["result"]
    assert raw_coverage(result, object_type)["Collection Status"] == "PARTIAL"
    assert raw_coverage(result, object_type)["Objects Found"] == 1
    assert result.errors[0]["query"] == "raw"
    assert "403" in result.errors[0]["error"]
    replay = load_raw(tmp_path)[0]
    assert replay.records == result.records
    assert replay.coverage == result.coverage
    assert replay.errors == result.errors
    assert_get_only_topology()

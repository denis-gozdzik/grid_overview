"""Live empty/predefined inventories and explicitly synthetic populated report cases."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from openpyxl import load_workbook
import requests

from infoblox_inventory.models import CollectionResult
from infoblox_inventory.report import write_reports
from infoblox_inventory.topology import TOPOLOGY_SHEETS, normalize_topology


CAPTURE = Path(__file__).parent / "fixtures" / "topology_lab_20260920"


def live_result():
    provenance = json.loads((CAPTURE / "provenance.json").read_text(encoding="utf-8"))
    return CollectionResult(
        grid="LAB-GRID", wapi_version="2.13.7", collected_at="2026-09-20T06:32:29Z",
        records={obj: json.loads((CAPTURE / "responses" / f"{obj}.json").read_text(encoding="utf-8"))["result"]
                 for obj in TOPOLOGY_SHEETS},
        schemas={obj: json.loads((CAPTURE / "schemas" / f"{obj}.json").read_text(encoding="utf-8"))
                 for obj in TOPOLOGY_SHEETS},
        coverage=[{"Grid": "LAB-GRID", "Area": obj, "Object": obj, "Query": "raw",
                   "Collection Status": "COMPLETE" if count else "EMPTY", "Objects Found": count}
                  for obj, count in provenance["live_counts"].items()],
    )


def rows(sheet):
    values = list(sheet.values)
    return [dict(zip(values[0], row)) for row in values[1:]]


def matrix(path):
    workbook = load_workbook(path)
    try:
        return {sheet.title: list(sheet.values) for sheet in workbook}
    finally:
        workbook.close()


def test_actual_topology_capture_hashes_counts_and_typed_definitions():
    provenance = json.loads((CAPTURE / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["kind"] == "actual_live_lab_topology_capture"
    for relative, expected in provenance["sha256"].items():
        assert hashlib.sha256((CAPTURE / relative).read_bytes()).hexdigest() == expected
    result = live_result()
    assert {obj: len(items) for obj, items in result.records.items()} == {
        "dhcpfailover": 0, "networktemplate": 0, "rangetemplate": 0,
        "fixedaddresstemplate": 0, "dhcpoptionspace": 1, "dhcpoptiondefinition": 95,
    }
    records = normalize_topology(result)
    assert len(records) == 96 and all(record.status == "COMPLETE" for record in records)
    space = next(record for record in records if record.object_type == "dhcpoptionspace")
    assert space.name == "DHCP" and space.space_type == "PREDEFINED_DHCP"
    assert space.comment is None
    definitions = [record for record in records if record.object_type == "dhcpoptiondefinition"]
    assert set(space.option_definitions) == {record.name for record in definitions}
    assert all(record.space == "DHCP" for record in definitions)
    lease = next(record for record in definitions if record.code == 51)
    assert lease.name == "dhcp-lease-time" and lease.type == "32-bit unsigned integer"


def test_live_capture_reports_preserve_empty_headers_coverage_and_repeat_offline(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Report generation must remain offline")
    monkeypatch.setattr(requests.Session, "request", no_network)
    result = live_result()
    before = deepcopy(result)
    write_reports([result], tmp_path / "first")
    write_reports([result], tmp_path / "second")
    assert result == before
    assert matrix(tmp_path / "first/current_state_inventory.xlsx") == matrix(tmp_path / "second/current_state_inventory.xlsx")
    workbook = load_workbook(tmp_path / "first/current_state_inventory.xlsx")
    assert set(TOPOLOGY_SHEETS.values()) | {"Template_Options"} <= set(workbook.sheetnames)
    for obj in ("dhcpfailover", "networktemplate", "rangetemplate", "fixedaddresstemplate"):
        sheet = workbook[TOPOLOGY_SHEETS[obj]]
        assert sheet.max_row == 1
        assert {"name", "object_ref", "normalization_status", "data_representation"} <= {cell.value for cell in sheet[1]}
    assert len(rows(workbook["Option_Definitions"])) == 95
    assert len(rows(workbook["Option_Spaces"])) == 1
    assert workbook["Template_Options"].max_row == 1
    coverage = rows(workbook["Coverage"])
    assert sum(row.get("Query") == "raw" and row["Collection Status"] == "EMPTY" for row in coverage) == 4
    assert sum(row.get("Query") == "normalization" and row["Collection Status"] == "COMPLETE" for row in coverage) == 2
    assert all(sheet.freeze_panes == "A2" and sheet.auto_filter.ref for sheet in workbook)
    workbook.close()


def test_synthetic_multigrid_templates_are_stored_rows_not_effective_claims(tmp_path):
    results = []
    for grid, stored in (("A", "43200"), ("B", "86400")):
        result = CollectionResult(grid=grid, records={
            "networktemplate": [{"_ref": "networktemplate/synthetic:shared", "name": "=1+1",
                                 "bootfile": "=boot.efi", "use_bootfile": False,
                                 "options": [{"num": 51, "value": stored, "use_option": True,
                                              "future_option": ["opaque"]}],
                                 "use_options": False, "future_field": {"unknown": True}}],
            "member": [{"_ref": "member/synthetic", "name": "member"}],
            "dhcpfailover": [{"name": "pair", "primary": "primary", "secondary": "secondary"}],
            "fixedaddresstemplate": [{"name": "fixed-template", "number_of_addresses": "invalid"}],
        }, schemas={"networktemplate": live_result().schemas["networktemplate"]},
            coverage=[{"Grid": grid, "Area": "Existing network templates", "Object": "networktemplate",
                       "Query": "raw", "Collection Status": "PARTIAL", "Objects Found": 1,
                       "Notes": "Synthetic second-page failure"}])
        results.append(result)
    before = deepcopy(results)
    write_reports(results, tmp_path)
    assert results == before
    workbook = load_workbook(tmp_path / "current_state_inventory.xlsx")
    templates = rows(workbook["Network_Templates"])
    assert {row["grid"] for row in templates} == {"A", "B"}
    assert all(row["name"] == "=1+1" and row["use_bootfile"] is False for row in templates)
    assert all(json.loads(row["extra_fields"])["future_field"] == {"unknown": True} for row in templates)
    options = rows(workbook["Template_Options"])
    assert {(row["grid"], row["stored_value"]) for row in options} == {("A", "43200"), ("B", "86400")}
    assert all(row["data_representation"] == "RAW_CONFIGURATION" and row["use_options"] is False for row in options)
    assert all("effective_value" not in row for row in options)
    assert all(json.loads(row["extra_fields"])["future_option"] == ["opaque"] for row in options)
    assert workbook["DHCP_Effective"].max_row == 1
    assert workbook["DHCP_Options"].max_row == 1
    assert {row["name"] for row in rows(workbook["Members_Failover"])} == {"member"}
    assert {row["name"] for row in rows(workbook["DHCP_Failover"])} == {"pair"}
    assert all(row["normalization_status"] == "PARTIAL" for row in rows(workbook["Fixed_Address_Templates"]))
    assert sum(row["Collection Status"] == "PARTIAL" and row["Query"] == "raw"
               for row in rows(workbook["Coverage"])) == 2
    assert not any(cell.data_type == "f" for sheet in workbook for row in sheet for cell in row)
    workbook.close()
    summary = (tmp_path / "current_state_summary.md").read_text(encoding="utf-8")
    assert "RAW_CONFIGURATION" in summary and "raw-query coverage" in summary


def test_core_only_report_does_not_gain_topology_sheets(tmp_path):
    write_reports([CollectionResult(grid="CORE", records={"networkview": [{"name": "default"}]})], tmp_path)
    workbook = load_workbook(tmp_path / "current_state_inventory.xlsx")
    assert not set(TOPOLOGY_SHEETS.values()).intersection(workbook.sheetnames)
    assert "Template_Options" not in workbook.sheetnames
    workbook.close()

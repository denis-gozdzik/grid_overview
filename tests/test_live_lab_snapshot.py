"""Regressions backed by byte-identical responses from the 2026-09-20 lab run."""
import hashlib
import json
from pathlib import Path

import pytest

from infoblox_inventory.normalize import normalize_options, normalize_scalars, parse_source_ref
from infoblox_inventory.storage import path_component


CAPTURE = Path(__file__).parent / "fixtures" / "live_lab_20260920"
OBJECTS = ("networkview", "grid:dhcpproperties", "member", "member:dhcpproperties", "network", "range")


def captured_arguments():
    raw, effective, schemas = {}, {}, {}
    for object_type in OBJECTS:
        for mode, records in (("raw", raw), ("effective", effective)):
            path = CAPTURE / path_component(object_type) / mode / "page-000001.json"
            if path.exists():
                records[object_type] = json.loads(path.read_text(encoding="utf-8"))["result"]
        schema_path = CAPTURE / "schema" / f"{path_component(object_type)}.json"
        if schema_path.exists():
            schemas[object_type] = json.loads(schema_path.read_text(encoding="utf-8"))
    return "LAB-GRID", "https://192.168.88.243", "2.13.7", raw, effective, schemas


def test_live_fixtures_match_the_original_response_hashes():
    provenance = json.loads((CAPTURE / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["kind"] == "actual_live_lab_capture"
    for relative, expected in provenance["sha256"].items():
        assert hashlib.sha256((CAPTURE / relative).read_bytes()).hexdigest() == expected


def test_real_range_reference_parses_address_pair_and_retains_original_ref():
    ref = captured_arguments()[3]["range"][0]["_ref"]
    source = parse_source_ref(ref)
    assert source["source_ref"] == ref
    assert source["source_level"] == "Range"
    assert source["source_network_view"] == "default"
    assert source["source_object"] == "10.77.10.100-10.77.10.199"


def test_real_lab_member_associations_and_available_scalar_evidence():
    arguments = captured_arguments()
    raw = arguments[3]
    assert raw["network"][0]["members"][0]["name"] == "infobloxlab.local"
    assert raw["range"][0]["member"]["name"] == "infobloxlab.local"
    assert raw["range"][0]["server_association_type"] == "MEMBER"
    rows = [row for row in normalize_scalars(*arguments) if row["parameter"] == "nextserver"]
    assert {row["object_type"]: row["effective_value"] for row in rows} == {
        "grid:dhcpproperties": "10.77.0.10", "member:dhcpproperties": None,
        "network": "10.77.0.30", "range": "10.77.0.40",
    }
    assert all(row["configured_here"] is True and row["inherited"] is False
               for row in rows if row["object_type"] != "member:dhcpproperties")
    member_row = next(row for row in rows if row["object_type"] == "member:dhcpproperties")
    assert member_row["raw_value"] == "10.77.0.20"
    assert member_row["status"] == "PARTIAL"
    range_row = next(row for row in rows if row["object_type"] == "range")
    assert range_row["source_object"] == "10.77.10.100-10.77.10.199"
    assert range_row["inheritance_details"]["source"] == ""


def test_real_lab_range_has_exact_four_effective_options_from_four_sources():
    arguments = captured_arguments()
    rows = [row for row in normalize_options(*arguments) if row["object_type"] == "range"]
    assert len(rows) == 4
    expected = {
        51: ("3600", True, "Range", "10.77.10.100-10.77.10.199"),
        3: ("10.77.10.1", False, "Network", "10.77.10.0/24"),
        6: ("10.77.0.60,10.77.0.61", False, "Member", "infobloxlab.local"),
        15: ("lab.local", False, "Grid", "LAB-GRID"),
    }
    for row in rows:
        assert tuple(row[key] for key in ("effective_value", "configured_here", "source_level", "source_object")) == expected[row["option_number"]]
        assert row["status"] == "COMPLETE"
        group = row["inheritance_details"]
        assert row["source_ref"] == (row["object_ref"] if not group["inherited"] else group["source"])
        if group["inherited"]:
            assert group["values"][0]["use_option"] is False


def test_real_lab_network_shadow_43200_never_overrides_effective_grid_lease():
    rows = normalize_options(*captured_arguments())
    lease, = [row for row in rows if row["object_type"] == "network" and row["option_number"] == 51]
    assert lease["raw_value"] == "43200"
    assert lease["raw_use_option"] is False
    assert lease["effective_value"] == "28800"
    assert lease["source_level"] == "Grid"
    assert lease["configured_here"] is False


def test_real_member_inheritance_query_returns_unwrapped_data_and_stays_unresolved():
    arguments = captured_arguments()
    assert arguments[3]["member:dhcpproperties"] == arguments[4]["member:dhcpproperties"]
    rows = [row for row in normalize_options(*arguments) if row["object_type"] == "member:dhcpproperties"]
    assert all(row["status"] == "PARTIAL" and row["effective_value"] is None for row in rows)
    lease, = [row for row in rows if row["option_number"] == 51]
    assert lease["raw_value"] == "43200"
    assert lease["raw_use_option"] is False


def test_real_missing_scalar_value_is_not_confused_with_not_defined_or_false():
    rows = {row["parameter"]: row for row in normalize_scalars(*captured_arguments()) if row["object_type"] == "range"}
    assert rows["pxe_lease_time"]["status"] == "NOT_CONFIGURED"
    assert rows["pxe_lease_time"]["source_ref"] == "NOT_DEFINED"
    assert rows["bootfile"]["status"] == "PARTIAL"
    assert rows["bootfile"]["effective_value"] is None
    assert rows["bootfile"]["source_level"] == "Grid"
    assert rows["enable_ddns"]["status"] == "COMPLETE"
    assert rows["enable_ddns"]["effective_value"] is False

from pathlib import Path

from openpyxl import load_workbook
import yaml

from infoblox_inventory.models import CollectionResult
from infoblox_inventory.report import write_reports
from infoblox_inventory.standardization import (
    build_standardization, exception_rows, grid_comparison_rows, load_decisions,
)
from infoblox_inventory.xlsx_validation import validate_xlsx


def _option(grid, obj_type, obj_ref, obj_name, value, *, configured_here, inherited, source_level, status="COMPLETE"):
    return {
        "grid": grid, "object_type": obj_type, "object_ref": obj_ref, "object_name": obj_name,
        "network_view": "default", "parent_network": "", "parameter": "dhcp-lease-time",
        "option_number": 51, "vendor_class": "DHCP", "effective_value": value,
        "configured_here": configured_here, "inherited": inherited, "multisource": False,
        "source_level": source_level, "source_object": obj_name if configured_here else "LAB",
        "source_ref": obj_ref if configured_here else "grid:dhcpproperties/example:LAB", "status": status,
    }


def _standardization(decisions=None):
    rows = [
        _option("LAB", "grid:dhcpproperties", "grid:dhcpproperties/example:LAB", "LAB", "28800",
                configured_here=True, inherited=False, source_level="Grid"),
        _option("LAB", "network", "network/example:10.0.0.0/24/default", "10.0.0.0/24", "28800",
                configured_here=False, inherited=True, source_level="Grid"),
        _option("LAB", "range", "range/example:10.0.0.10/10.0.0.20/default", "10.0.0.10-10.0.0.20", "3600",
                configured_here=True, inherited=False, source_level="Range"),
    ]
    return build_standardization([CollectionResult("LAB")], [], [], rows, decisions or {})


def _lease(rows):
    found = [row for row in rows if row["Parameter ID"] == "dhcp.lease_time"]
    assert len(found) == 1
    return found[0]


def test_common_value_and_local_override_are_observations_not_approval():
    row = _lease(_standardization())
    assert row["Observed Values"] == "28800 (2); 3600 (1)"
    assert row["Common Observed Value"] == "28800"
    assert row["Common Value Count"] == 2
    assert row["Common Value %"] == 66.7
    assert row["Local Override Count"] == 1
    assert row["Override Eligible Objects"] == 2
    assert row["Local Override %"] == 50.0
    assert row["Consistency Classification"] == "MULTIPLE_VALUES"
    assert row["Decision Status"] == "PENDING"
    assert row["Approved Target"] == ""
    pending = exception_rows(_standardization())
    assert [(row["Object Type"], row["Assessment State"]) for row in pending] == [("range", "PENDING_DECISION")]


def test_approved_target_creates_deviation_only_after_human_decision():
    decisions = {"dhcp.lease_time": {
        "status": "APPROVED", "approved_target": "28800", "exceptions_allowed": False,
        "proposed_target": None, "exception_rule": "", "owner": "PO", "decision_date": "2026-09-21",
        "notes": "", "comparison_mode": "exact", "approved_exceptions": [],
    }}
    rows = exception_rows(_standardization(decisions))
    assert len(rows) == 1
    assert rows[0]["Object Type"] == "range"
    assert rows[0]["Assessment State"] == "DEVIATION"
    assert rows[0]["Approved Target"] == "28800"
    assert rows[0]["Owner"] == "PO"


def test_explicit_exception_selector_can_approve_a_deviation():
    ref = "range/example:10.0.0.10/10.0.0.20/default"
    decisions = {"dhcp.lease_time": {
        "status": "APPROVED", "approved_target": 28800, "exceptions_allowed": True,
        "proposed_target": None, "exception_rule": "Short-lived test range", "owner": "PO", "decision_date": "",
        "notes": "", "comparison_mode": "exact", "approved_exceptions": [{"object_ref": ref}],
    }}
    row, = exception_rows(_standardization(decisions))
    assert row["Assessment State"] == "APPROVED_EXCEPTION"
    assert row["Exception Rule"] == "Short-lived test range"


def test_single_grid_comparison_is_explicitly_not_applicable():
    rows, headers = grid_comparison_rows(_standardization(), ["LAB"])
    assert "LAB" in headers
    assert rows == [{
        "Category": "Comparison", "Parameter ID": "", "Parameter": "Cross-Grid comparison",
        "LAB": "", "Distinct Values": "", "Common Observed Value": "", "Consistency": "NOT_APPLICABLE",
        "Local Overrides": "", "Coverage": "", "Notes": "Cross-Grid comparison requires at least two Grids.",
    }]


def test_decision_loader_rejects_unknown_ids_and_never_infers_approval(tmp_path):
    path = tmp_path / "decisions.yaml"
    path.write_text("decisions:\n  dhcp.lease_time:\n    status: UNDER_REVIEW\n    proposed_target: 28800\n", encoding="utf-8")
    loaded = load_decisions(path)
    assert loaded["dhcp.lease_time"]["status"] == "UNDER_REVIEW"
    assert loaded["dhcp.lease_time"]["approved_target"] is None
    path.write_text("decisions:\n  made.up.parameter:\n    status: APPROVED\n", encoding="utf-8")
    try:
        load_decisions(path)
    except ValueError as exc:
        assert "Unknown standardization decision IDs" in str(exc)
    else:
        raise AssertionError("unknown decision id should fail")


def test_report_puts_decision_support_first_and_uses_decision_yaml(tmp_path):
    grid_ref = "grid:dhcpproperties/example:LAB"
    network_ref = "network/example:10.0.0.0/24/default"
    range_ref = "range/example:10.0.0.10/10.0.0.20/default"
    result = CollectionResult(
        grid="LAB", grid_url="https://grid", wapi_version="2.13.7", collected_at="2026-09-21T06:00:00Z",
        records={
            "grid:dhcpproperties": [{"_ref": grid_ref, "options": [{"num": 51, "name": "dhcp-lease-time", "value": "28800", "use_option": True}]}],
            "network": [{"_ref": network_ref, "network": "10.0.0.0/24", "network_view": "default",
                         "options": [{"num": 51, "name": "dhcp-lease-time", "value": "43200", "use_option": False}]}],
            "range": [{"_ref": range_ref, "start_addr": "10.0.0.10", "end_addr": "10.0.0.20", "network_view": "default",
                       "options": [{"num": 51, "name": "dhcp-lease-time", "value": "3600", "use_option": True}]}],
        },
        effective_records={
            "network": [{"_ref": network_ref, "network": "10.0.0.0/24", "network_view": "default",
                         "options": [{"inherited": True, "source": grid_ref,
                                      "values": [{"num": 51, "name": "dhcp-lease-time", "value": "28800", "use_option": False}]}]}],
            "range": [{"_ref": range_ref, "start_addr": "10.0.0.10", "end_addr": "10.0.0.20", "network_view": "default",
                       "options": [{"inherited": False, "source": "",
                                    "values": [{"num": 51, "name": "dhcp-lease-time", "value": "3600", "use_option": True}]}]}],
        },
        schemas={"network": {"fields": [{"name": "options", "overridden_by": "use_options"}]},
                 "range": {"fields": [{"name": "options", "overridden_by": "use_options"}]}},
        coverage=[{"Grid": "LAB", "Area": "DHCP options and inheritance", "Object": "network", "Query": "effective",
                   "Field": "", "Collection Status": "COMPLETE", "Objects Found": 1, "Notes": ""}],
    )
    decisions = tmp_path / "decisions.yaml"
    decisions.write_text(yaml.safe_dump({"decisions": {"dhcp.lease_time": {
        "status": "APPROVED", "approved_target": 28800, "exceptions_allowed": False,
        "owner": "Infoblox Product Owner",
    }}}), encoding="utf-8")
    output = tmp_path / "report"
    write_reports([result], output, decisions_path=decisions)
    validated = validate_xlsx(output / "current_state_inventory.xlsx")
    assert validated["zip_crc_ok"] is True
    workbook = load_workbook(output / "current_state_inventory.xlsx")
    try:
        assert workbook.sheetnames[:7] == [
            "Overview", "Standardization", "Decisions", "Exceptions", "Grid_Comparison", "Coverage", "Manual_Review"
        ]
        assert workbook["Overview"]["A1"].value == "Infoblox Current State & Standardization Assessment"
        decision_headers = [cell.value for cell in workbook["Decisions"][1]]
        rows = [dict(zip(decision_headers, values)) for values in workbook["Decisions"].iter_rows(min_row=2, values_only=True)]
        lease = [row for row in rows if row["Decision ID"] == "dhcp.lease_time"][0]
        assert lease["Status"] == "APPROVED"
        assert lease["Approved Target"] == "28800"
        exception_headers = [cell.value for cell in workbook["Exceptions"][1]]
        exceptions = [dict(zip(exception_headers, values)) for values in workbook["Exceptions"].iter_rows(min_row=2, values_only=True)]
        assert [(row["Object Type"], row["Assessment State"]) for row in exceptions] == [("range", "DEVIATION")]
    finally:
        workbook.close()
    template = yaml.safe_load((output / "standardization_decisions.template.yaml").read_text(encoding="utf-8"))
    assert template["decisions"]["dhcp.lease_time"]["status"] == "APPROVED"

def test_multi_grid_comparison_is_parameter_centric_and_descriptive():
    rows = [
        _option("GRID-A", "network", "network/a", "10.0.0.0/24", "28800",
                configured_here=False, inherited=True, source_level="Grid"),
        _option("GRID-B", "network", "network/b", "10.1.0.0/24", "43200",
                configured_here=False, inherited=True, source_level="Grid"),
    ]
    analysis = build_standardization([CollectionResult("GRID-A"), CollectionResult("GRID-B")], [], [], rows, {})
    lease = _lease(analysis)
    assert lease["Consistency Classification"] == "MULTIPLE_VALUES"
    assert lease["Common Observed Value"] == ""  # tie: no implied standard
    comparison, headers = grid_comparison_rows(analysis, ["GRID-A", "GRID-B"])
    assert {"GRID-A", "GRID-B"} <= set(headers)
    row = next(item for item in comparison if item["Parameter ID"] == "dhcp.lease_time")
    assert row["GRID-A"] == "28800 (1)"
    assert row["GRID-B"] == "43200 (1)"
    assert row["Consistency"] == "MULTIPLE_VALUES"


def test_cli_parser_accepts_decision_overlay_for_offline_reporting():
    from infoblox_inventory.cli import build_parser

    args = build_parser().parse_args(["--offline", "raw", "--decisions", "decisions.yaml"])
    assert args.offline == ["raw"]
    assert args.decisions == "decisions.yaml"

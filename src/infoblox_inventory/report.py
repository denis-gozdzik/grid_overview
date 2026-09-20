from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo

from .analysis import compare_options, naming_analysis
from .models import CollectionResult
from .normalize import normalize_options, normalize_scalars
from .topology import (TOPOLOGY_SHEETS, normalize_topology, topology_coverage,
                       topology_excel_rows, topology_headers, topology_option_rows)
from .reservations import (RESERVATION_SHEETS, normalize_reservations, reservation_coverage,
                           reservation_excel_rows, reservation_headers, reservation_option_rows,
                           reservation_relationship_rows)


def _json_value(value: Any) -> Any:
    return json.dumps(value, sort_keys=True, default=str) if isinstance(value, (dict, list)) else value


def _markdown_value(value: Any) -> str:
    return str(_json_value(value) if value is not None else "").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def write_reports(results: list[CollectionResult], output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    all_options: list[dict[str, Any]] = []
    all_scalars: list[dict[str, Any]] = []
    naming: list[dict[str, Any]] = []
    topology_records = []
    reservation_records = []
    stored_only = set(TOPOLOGY_SHEETS) | (set(RESERVATION_SHEETS) - {"fixedaddress"})
    results = sorted(results, key=lambda result: result.grid)
    for result in results:
        # Stored reusable configuration has its own rows, without effective-value claims.
        arguments = (result.grid, result.grid_url, result.wapi_version,
                     {key: rows for key, rows in result.records.items() if key not in stored_only},
                     {key: rows for key, rows in result.effective_records.items() if key not in stored_only},
                     result.schemas)
        all_options.extend(normalize_options(*arguments))
        all_scalars.extend(normalize_scalars(*arguments))
        naming.extend({**row, "grid": result.grid} for row in naming_analysis(result.records))
        topology_records.extend(normalize_topology(result))
        reservation_records.extend(normalize_reservations(result))
    coverage = ([row for result in results for row in result.coverage]
                + topology_coverage(topology_records) + reservation_coverage(reservation_records))
    for result in results:
        filter_count = sum(len(rows) for key, rows in result.records.items()
                           if key in RESERVATION_SHEETS and (key.startswith("filter") or key == "macfilteraddress"))
        if filter_count:
            coverage.append({"Grid": result.grid, "Area": "DHCP filters and MAC filters", "Object": "",
                             "Query": "policy_interpretation", "Collection Status": "MANUAL_REVIEW_REQUIRED",
                             "Objects Found": filter_count,
                             "Notes": "Configured names, expressions and references do not establish deployed permit/deny policy; "
                                      "consumer assignments outside this increment are not assessed."})
    differences = compare_options(all_options)
    manual_rows = [row for row in coverage if row.get("Collection Status") == "MANUAL_REVIEW_REQUIRED"]
    sheets = {
        "Grid_Summary": [{"Grid": result.grid, "URL": result.grid_url, "WAPI Version": result.wapi_version,
                          "Collected At": result.collected_at, "Object": key,
                          "Raw Count": len(result.records.get(key, [])),
                          "Effective Count": len(result.effective_records.get(key, [])), "Errors": len(result.errors)}
                         for result in results
                         for key in (sorted(set(result.records) | set(result.effective_records)) or [""])],
        "Coverage": coverage,
        "Errors": [row for result in results for row in result.errors],
        "DHCP_Effective": all_scalars,
        "DHCP_Options": all_options,
        "DHCP_Raw": [{"grid": result.grid, "object_type": object_type, **row}
                     for result in results for object_type, records in sorted(result.records.items())
                     for row in records if "options" in row or object_type.endswith(":dhcpproperties")
                     or any(key.startswith("use_") for key in row)],
        "Differences": differences,
        "Naming_Analysis": naming,
        "Manual_Review": manual_rows,
    }
    for result in results:
        for object_type, rows in sorted(result.records.items()):
            if object_type in TOPOLOGY_SHEETS:
                sheets.setdefault(TOPOLOGY_SHEETS[object_type], [])
                continue
            if object_type in RESERVATION_SHEETS:
                sheets.setdefault(RESERVATION_SHEETS[object_type], [])
                continue
            sheets.setdefault(_sheet_name(object_type), []).extend(
                {"grid": result.grid, **{key: _json_value(value) for key, value in row.items()}}
                for row in rows)
    topology_rows = topology_excel_rows(topology_records)
    sheet_headers = {}
    for object_type, name in TOPOLOGY_SHEETS.items():
        if name in sheets:
            sheets[name].extend(topology_rows[object_type])
            sheet_headers[name] = topology_headers(object_type)
    reservation_rows = reservation_excel_rows(reservation_records)
    for object_type, name in RESERVATION_SHEETS.items():
        if name in sheets:
            sheets[name].extend(reservation_rows[object_type])
            sheet_headers[name] = reservation_headers(object_type)
    if any(key in RESERVATION_SHEETS for result in results for key in result.records):
        sheets["Reservation_Options"] = reservation_option_rows(reservation_records)
        sheet_headers["Reservation_Options"] = [
            "grid", "object_type", "object_ref", "name", "data_representation", "normalization_status",
            "issues", "option_field", "option_index", "option_name", "code", "vendor", "user_class",
            "option_type", "stored_value", "use_option", "use_options", "extra_fields",
        ]
        sheets["Reservation_Links"] = reservation_relationship_rows(reservation_records)
        sheet_headers["Reservation_Links"] = [
            "grid", "object_type", "object_ref", "name", "data_representation", "normalization_status",
            "issues", "relationship_field", "relationship_index", "target", "configured_rule_type",
            "use_logic_filter_rules", "relationship_data", "interpretation",
        ]
    if any(object_type.endswith("template") for result in results for object_type in result.records
           if object_type in TOPOLOGY_SHEETS):
        sheets["Template_Options"] = topology_option_rows(topology_records)
        sheet_headers["Template_Options"] = [
            "grid", "object_type", "object_ref", "name", "data_representation", "normalization_status",
            "issues", "option_name", "code", "vendor", "stored_value", "use_option", "use_options", "extra_fields",
        ]
    workbook = Workbook()
    workbook.remove(workbook.active)
    for index, (name, rows) in enumerate(sheets.items(), start=1):
        sheet = workbook.create_sheet(name[:31])
        headers = sheet_headers.get(name) or sorted({key for row in rows for key in row}) or ["Status"]
        sheet.append(headers)
        for row in sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, default=str)):
            values = [_json_value(row.get(header, "")) for header in headers]
            values = [re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", lambda match: f"\\u{ord(match[0]):04x}", value)
                      if isinstance(value, str) else value for value in values]
            sheet.append(values)
        # WAPI names/comments/options are data, including strings beginning with '='.
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            width = min(max(max(len(str(cell.value or "")) for cell in column) + 2, 10), 45)
            sheet.column_dimensions[column[0].column_letter].width = width
        if rows:
            ref = f"A1:{sheet.cell(sheet.max_row, sheet.max_column).coordinate}"
            table = Table(displayName=f"InventoryTable{index}", ref=ref)
            table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
            sheet.add_table(table)
    workbook.save(output / "current_state_inventory.xlsx")
    summary = ["# Infoblox current-state inventory", "",
               "This is an evidence-gathering report; common values are not approved standards.", "",
               "Raw/local values and WAPI effective inheritance evidence are reported separately. "
               "PARTIAL normalized rows have no confirmed effective value.", "", "## Grids collected", "",
               "| Grid | WAPI version | Collection timestamp (UTC) |", "| --- | --- | --- |"]
    for result in results:
        summary.append(f"| {_markdown_value(result.grid)} | {_markdown_value(result.wapi_version)} | "
                       f"{_markdown_value(result.collected_at)} |")
    summary.extend(["", "## Collection errors", ""])
    errors = [row for result in results for row in result.errors]
    summary.extend(f"- {_markdown_value(row.get('grid'))}: {_markdown_value(row.get('object_type'))}: "
                   f"{_markdown_value(row.get('error'))}" for row in errors)
    if not errors:
        summary.append("No collection errors recorded.")
    summary.extend(["", "## Coverage", "",
                    "Status counts summarize collection, query, and field observations. "
                    "The workbook Coverage sheet contains object/query/field details and notes.", "",
                    "| Grid | Area | Status counts |", "| --- | --- | --- |"])
    coverage_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in coverage:
        coverage_counts[(str(row.get("Grid", "")), str(row.get("Area", "")))][str(row.get("Collection Status", ""))] += 1
    for (grid, area), counts in sorted(coverage_counts.items()):
        summary.append(f"| {_markdown_value(grid)} | {_markdown_value(area)} | "
                       + ", ".join(f"{_markdown_value(status)}: {count}" for status, count in sorted(counts.items())) + " |")
    if any(object_type in TOPOLOGY_SHEETS for result in results for object_type in result.records):
        summary.extend(["", "## Reusable DHCP configuration", "",
                        "Topology sheets show typed RAW_CONFIGURATION values and observed use flags, "
                        "not effective values for objects created from templates. Template_Options exposes "
                        "stored option values separately. Empty inventories retain column headers; "
                        "consult Coverage to distinguish EMPTY, unavailable, and failed queries. "
                        "Normalization coverage describes parsed records only; raw-query coverage "
                        "remains authoritative for collection completeness. Unknown fields remain in "
                        "extra_fields and complete responses remain in the raw archive."])
    if any(key in RESERVATION_SHEETS for result in results for key in result.records):
        summary.extend(["", "## DHCP reservations and filters", "",
                        "Reservation/filter sheets contain typed RAW_CONFIGURATION evidence. "
                        "Reservation_Options and Reservation_Links retain nested values, use flags and source indexes. "
                        "Fixed-address effective evidence continues through the existing DHCP sheets. "
                        "Host DHCP configuration status concerns explicit IPv4 configure_for_dhcp flags only; "
                        "it does not assess IPv6, service activation or lease availability. Roaming hosts are not "
                        "classified as fixed-IP reservations. Template origin is unavailable when WAPI exposes "
                        "only a write-only template field. Filter names, including Corporate or Allowed, imply "
                        "no policy meaning. Consumers outside this collection are not assessed. "
                        "DDNS/EA fields are retained solely as reservation metadata. For superhostchild, "
                        "an empty complete parent inventory means no child request; Coverage records that dependency."])
    changed = [row for row in differences if row["classification"] in {"DIFFERENT", "SOURCE_DIFFERENCE"}]
    summary.extend(["", "## Key differences", "",
                    "Comparison currently covers confirmed DHCP options matched by queried object and Network View. "
                    "Unresolved and multisource rows are excluded. Scalar, filter, failover, naming, "
                    "and other cross-Grid comparisons remain to be implemented.", ""])
    summary.extend(f"- {_markdown_value(row['grid'])}: {_markdown_value(row['object/context'])}, "
                   f"{_markdown_value(row['parameter'])}: {_markdown_value(row['observed_value'])} "
                   f"({row['classification']})." for row in changed[:20])
    if not changed:
        summary.append("No differences identified among comparable, confirmed effective DHCP options. "
                       "Unresolved and multisource rows are excluded from this comparison.")
    candidates = [row for row in all_options + all_scalars
                  if row["configured_here"] is True and row["object_type"] != "grid:dhcpproperties"]
    summary.extend(["", "## Local exception candidates", "",
                    f"{len(candidates)} confirmed local parameter/option overrides; local configuration alone "
                    "does not establish a policy exception."])
    summary.extend(f"- {_markdown_value(row['grid'])}: {_markdown_value(row['object_name'])}, "
                   f"{_markdown_value(row['parameter'])}: {_markdown_value(row['effective_value'])}."
                   for row in candidates[:20])
    inherited = [row for row in all_options + all_scalars if row["inherited"] is True]
    multiple = [row for row in all_options + all_scalars if row["multisource"] is True]
    summary.extend(["", "## Inheritance observations", "",
                    f"{len(inherited)} rows indicate inheritance; {len(multiple)} rows indicate multiple sources. "
                    "Source references and complete inheritance groups are retained in the workbook.", "",
                    "## Manual review", "",
                    "Approval process and documentation requirements require confirmation with Grid owners. "
                    "WAPI observations do not establish organizational policy.", "", "## Files generated", "",
                    "- current_state_inventory.xlsx", "- current_state_summary.md", "- manual_review.md"])
    (output / "current_state_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    manual = ["# Manual review required", "", "Approval workflow and formal documentation policy are not reliably represented by DHCP WAPI objects.", ""]
    manual.extend(f"- {result.grid}: confirm approval process and documentation policy with Grid owners." for result in results)
    (output / "manual_review.md").write_text("\n".join(manual) + "\n", encoding="utf-8")


def _sheet_name(object_type: str) -> str:
    return {"networkview": "Network_Views", "network": "Networks", "range": "Ranges",
            "grid:dhcpproperties": "Grid_DHCP", "member:dhcpproperties": "Member_DHCP",
            "member": "Members_Failover", **TOPOLOGY_SHEETS, **RESERVATION_SHEETS,
            "extensibleattributedef": "Extensible_Attributes"}.get(
                object_type, re.sub(r"[\\/*?:\[\]]", "_", object_type)[:31])

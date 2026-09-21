from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.formatting.rule import FormulaRule
from openpyxl.worksheet.table import Table, TableStyleInfo

from .analysis import compare_options, naming_analysis
from .models import CollectionResult
from .dataset import combine_collections
from .overview import OVERVIEW_HEADERS, overview_rows
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


def _excel_text(value: Any) -> Any:
    value = _json_value(value)
    return (re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", lambda match: f"\\u{ord(match[0]):04x}", value)
            if isinstance(value, str) else value)


ASSESSMENT_COLUMNS = [
    ("Grid", "grid"), ("Object Type", "object_type"), ("Object", "object_name"),
    ("Network View", "network_view"), ("Parent Network", "parent_network"),
    ("Parameter", "parameter"), ("Option Number", "option_number"),
    ("Effective Value", "effective_value"), ("Configured Here", "configured_here"),
    ("Inherited", "inherited"), ("Source Level", "source_level"),
    ("Source Object", "source_object"), ("Status", "status"),
]


def assessment_table(rows, *, ddns=False):
    columns = [("DDNS Parameter" if ddns and label == "Parameter" else label, key)
               for label, key in ASSESSMENT_COLUMNS if not (ddns and key == "option_number")]
    primary = {key for _, key in columns}
    technical = sorted({key for row in rows for key in row} - primary)
    return ([{**{label: row.get(key) for label, key in columns},
              **{key: row.get(key) for key in technical}} for row in rows],
            [label for label, _ in columns] + technical)


def _effective_query_summary(result, object_type):
    present = object_type in result.effective_records
    statuses = sorted({row.get("Collection Status", "PARTIAL") for row in result.coverage
                       if row.get("Object") == object_type and row.get("Query") == "effective"})
    return {"Effective Query Rows": len(result.effective_records[object_type]) if present else None,
            "Effective Query State": (", ".join(statuses) or "QUERY_STATUS_UNAVAILABLE") if present
                                     else "NOT_REQUESTED",
            "Effective Count Meaning": "Response object count, not configured effective fields. "
                + ("See query coverage and normalized field statuses." if present else
                   "No separate effective response was captured; this does not imply absent configuration.")}


def _write_inventory_sheet(workbook: Workbook, index: int, name: str,
                           rows: list[dict[str, Any]], headers: list[str], *,
                           preserve_order: bool = False) -> None:
    sheet = workbook.create_sheet(name[:31])
    # Excel table headers must be nonempty strings and unique ignoring case.
    # Keep source keys separate so display-name repairs never move or lose data.
    labels: list[str] = []
    used: set[str] = set()
    for key in headers:
        base = str(_excel_text(key)).strip()[:255] or "Column"
        label = base
        suffix = 2
        while label.casefold() in used:
            ending = f" ({suffix})"
            label = base[:255 - len(ending)] + ending
            suffix += 1
        used.add(label.casefold())
        labels.append(label)
    sheet.append(labels)
    ordered = rows if preserve_order else sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, default=str))
    for row in ordered:
        sheet.append([_excel_text(row.get(header, "")) for header in headers])
    # WAPI names/comments/options are literal data, including leading '='.
    for row in sheet.iter_rows():
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    sheet.freeze_panes = "A2"
    for column in sheet.columns:
        width = min(max(max(len(str(cell.value or "")) for cell in column) + 2, 10), 45)
        sheet.column_dimensions[column[0].column_letter].width = width
    if rows:
        table = Table(displayName=f"InventoryTable{index}", ref=sheet.dimensions)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        # The table owns its AutoFilter. Adding a worksheet AutoFilter over
        # this range causes Microsoft Excel to repair/reject the table parts.
        sheet.add_table(table)
    # An empty inventory keeps its headers but has neither a table nor filter.


def _style_overview(sheet) -> None:
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 85
    widths = {'A': 18, 'B': 20, 'C': 30, 'D': 60, 'E': 72}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    for cell in sheet[1]:
        cell.fill = PatternFill('solid', fgColor='17365D')
        cell.font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        cell.alignment = Alignment(vertical='center', wrap_text=True)
    sheet.row_dimensions[1].height = 30
    previous_section = None
    for row in sheet.iter_rows(min_row=2):
        section = (row[0].value, row[1].value)
        for cell in row:
            cell.font = Font(name='Calibri', size=11)
            cell.alignment = Alignment(vertical='top', wrap_text=True)
            if section != previous_section:
                cell.fill = PatternFill('solid', fgColor='E7EFF8')
                cell.font = Font(name='Calibri', size=11, bold=True, color='17365D')
        if isinstance(row[3].value, (int, float)) and not isinstance(row[3].value, bool):
            row[3].number_format = '#,##0'
        lines = max(sum(max(1, (len(line) + int(widths[cell.column_letter]) - 1)
                            // int(widths[cell.column_letter]))
                        for line in str(cell.value or '').split('\n')) for cell in row)
        sheet.row_dimensions[row[0].row].height = min(max(23, 16 * (lines + 1)), 180)
        previous_section = section
    if sheet.max_row > 1:
        for status, color in [('ERROR', 'FCE4D6'), ('PARTIAL', 'FFF2CC')]:
            sheet.conditional_formatting.add(
                f'D2:D{sheet.max_row}', FormulaRule(
                    formula=[f'ISNUMBER(SEARCH("{status}",$D2))'],
                    fill=PatternFill('solid', fgColor=color)))
    sheet.print_title_rows = '1:1'
    sheet.print_options.horizontalCentered = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_area = sheet.dimensions


def write_reports(results: list[CollectionResult], output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    all_options: list[dict[str, Any]] = []
    all_scalars: list[dict[str, Any]] = []
    naming: list[dict[str, Any]] = []
    topology_records = []
    reservation_records = []
    stored_only = set(TOPOLOGY_SHEETS) | (set(RESERVATION_SHEETS) - {"fixedaddress"})
    results = combine_collections(results)
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
    differences = (compare_options(all_options) if len(results) > 1 else
                   [{"grid": results[0].grid, "classification": "NOT_APPLICABLE",
                     "notes": "Cross-Grid comparison needs at least two Grids; only one Grid is present."}]
                   if results else [])
    effective_rows, effective_headers = assessment_table(all_scalars)
    manual_rows = [row for row in coverage if row.get("Collection Status") == "MANUAL_REVIEW_REQUIRED"]
    sheets = {
        **({'Overview': overview_rows(results, coverage, all_scalars, all_options)} if results else {}),
        "Grid_Summary": [{"Grid": result.grid, "URL": result.grid_url, "WAPI Version": result.wapi_version,
                          "Collected At": result.collected_at, "Object": key,
                          "Raw Count": len(result.records.get(key, [])),
                          **_effective_query_summary(result, key), "Errors": len(result.errors)}
                         for result in results
                         for key in (sorted(set(result.records) | set(result.effective_records)) or [""])],
        "Coverage": coverage,
        "Errors": [row for result in results for row in result.errors],
        "DHCP_Effective": effective_rows,
        "DHCP_Options": all_options,
        "DHCP_Raw": [{"grid": result.grid, "object_type": object_type, **row}
                     for result in results for object_type, records in sorted(result.records.items())
                     for row in records if "options" in row or object_type.endswith(":dhcpproperties")
                     or any(key.startswith("use_") for key in row)],
        "Differences": differences,
        "Naming_Analysis": naming,
        "Manual_Review": manual_rows,
        "Collection_Sources": [row for result in results for row in result.collection_sources],
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
    sheet_headers = {'Overview': OVERVIEW_HEADERS, 'DHCP_Effective': effective_headers}
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
        headers = sheet_headers.get(name) or sorted({key for row in rows for key in row}) or ["Status"]
        _write_inventory_sheet(workbook, index, name, rows, headers, preserve_order=name == 'Overview')
        if name == 'Overview':
            _style_overview(workbook[name])
    workbook.save(output / "current_state_inventory.xlsx")
    summary = ["# Infoblox current-state inventory", "",
               "This is an evidence-gathering report; common values are not approved standards.", "",
               "Raw/local values and WAPI effective inheritance evidence are reported separately. "
               "PARTIAL normalized rows have no confirmed effective value.", "", "## Grids collected", "",
               "| Grid | WAPI version | Collection timestamp (UTC) |", "| --- | --- | --- |"]
    for result in results:
        summary.append(f"| {_markdown_value(result.grid)} | {_markdown_value(result.wapi_version)} | "
                       f"{_markdown_value(result.collected_at)} |")
    summary.extend(["", "Start with the workbook Overview for inventory counts, coverage and observed effective DHCP values. "
                    "Collection_Sources retains each object's collection timestamp. Combining archives is not an atomic "
                    "appliance snapshot; conflicting object snapshots are rejected. RAW and effective evidence remain separate."])
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
    if len(results) < 2:
        summary.append("Cross-Grid comparison is not yet applicable: at least two Grids are required.")
    elif not changed:
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

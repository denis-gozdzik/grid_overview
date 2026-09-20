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
    results = sorted(results, key=lambda result: result.grid)
    for result in results:
        arguments = (result.grid, result.grid_url, result.wapi_version, result.records,
                     result.effective_records, result.schemas)
        all_options.extend(normalize_options(*arguments))
        all_scalars.extend(normalize_scalars(*arguments))
        naming.extend({**row, "grid": result.grid} for row in naming_analysis(result.records))
    differences = compare_options(all_options)
    manual_rows = [row for result in results for row in result.coverage
                   if row.get("Collection Status") == "MANUAL_REVIEW_REQUIRED"]
    sheets = {
        "Grid_Summary": [{"Grid": result.grid, "URL": result.grid_url, "WAPI Version": result.wapi_version,
                          "Collected At": result.collected_at, "Object": key,
                          "Raw Count": len(result.records.get(key, [])),
                          "Effective Count": len(result.effective_records.get(key, [])), "Errors": len(result.errors)}
                         for result in results
                         for key in (sorted(set(result.records) | set(result.effective_records)) or [""])],
        "Coverage": [row for result in results for row in result.coverage],
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
            sheets.setdefault(_sheet_name(object_type), []).extend(
                {"grid": result.grid, **{key: _json_value(value) for key, value in row.items()}}
                for row in rows)
    workbook = Workbook()
    workbook.remove(workbook.active)
    for index, (name, rows) in enumerate(sheets.items(), start=1):
        sheet = workbook.create_sheet(name[:31])
        headers = sorted({key for row in rows for key in row}) or ["Status"]
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
    for result in results:
        for row in result.coverage:
            coverage_counts[(result.grid, str(row.get("Area", "")))][str(row.get("Collection Status", ""))] += 1
    for (grid, area), counts in sorted(coverage_counts.items()):
        summary.append(f"| {_markdown_value(grid)} | {_markdown_value(area)} | "
                       + ", ".join(f"{_markdown_value(status)}: {count}" for status, count in sorted(counts.items())) + " |")
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
            "fixedaddress": "Fixed_Reservations", "networktemplate": "Network_Templates",
            "rangetemplate": "Range_Templates", "member": "Members_Failover",
            "dhcpfailover": "Members_Failover", "dhcpoptiondefinition": "Option_Definitions",
            "filtermac": "Filters", "filteroption": "Filters", "extensibleattributedef": "Extensible_Attributes"}.get(
                object_type, re.sub(r"[\\/*?:\[\]]", "_", object_type)[:31])

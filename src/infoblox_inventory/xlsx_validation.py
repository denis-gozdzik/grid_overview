"""Independent ZIP/OOXML checks for the inventory workbook's table contract.

This validates serialized parts, not openpyxl's in-memory model. It detects the
known Excel repair conditions; passing is not a substitute for opening in Excel.
The report writer intentionally supports tables with one header row and at least
one data row. Empty sheets must not have tables.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import posixpath
import re
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"s": MAIN, "r": REL}


class XlsxValidationError(ValueError):
    """The serialized workbook violates an inventory OOXML invariant."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise XlsxValidationError(message)


def _integer(value: str | None, context: str, minimum: int = 1) -> int:
    _require(value is not None and bool(re.fullmatch(r"[0-9]+", value)),
             f"{context}: expected integer, got {value!r}")
    result = int(value)
    _require(result >= minimum, f"{context}: must be at least {minimum}")
    return result


def _rectangle(ref: str | None, context: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"\$?([A-Z]+)\$?([1-9][0-9]*)(?::\$?([A-Z]+)\$?([1-9][0-9]*))?", ref or "")
    _require(match is not None, f"{context}: invalid ref {ref!r}")
    first_col, first_row, last_col, last_row = match.groups()

    def column(value: str) -> int:
        number = 0
        for char in value:
            number = number * 26 + ord(char) - ord("A") + 1
        return number

    result = column(first_col), int(first_row), column(last_col or first_col), int(last_row or first_row)
    _require(1 <= result[0] <= result[2] <= 16384 and 1 <= result[1] <= result[3] <= 1048576,
             f"{context}: ref outside Excel bounds or reversed: {ref!r}")
    return result


def _overlaps(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    return not (left[2] < right[0] or right[2] < left[0] or left[3] < right[1] or right[3] < left[1])


def _cell_ref(column: int, row: int) -> str:
    letters = ""
    while column:
        column, digit = divmod(column - 1, 26)
        letters = chr(65 + digit) + letters
    return f"{letters}{row}"


def validate_xlsx(path: str | Path) -> dict[str, Any]:
    """Raise :class:`XlsxValidationError` on defects; return counts otherwise.

    Only reads ``path``. No network, Excel automation, or workbook mutation.
    Returned ``sheet_rows`` excludes each sheet's first/header row.
    """
    try:
        with ZipFile(path) as archive:
            filenames = archive.namelist()
            _require(len(filenames) == len(set(filenames)), "Duplicate ZIP part names")
            bad_part = archive.testzip()
            _require(bad_part is None, f"ZIP CRC failure: {bad_part}")
            parts = {name: archive.read(name) for name in filenames if not name.endswith("/")}
    except (BadZipFile, OSError) as exc:
        raise XlsxValidationError(f"Cannot read XLSX ZIP: {exc}") from exc

    def xml(name: str) -> ET.Element:
        _require(name in parts, f"Missing package part: {name}")
        try:
            return ET.fromstring(parts[name])
        except ET.ParseError as exc:
            raise XlsxValidationError(f"Malformed XML in {name}: {exc}") from exc

    relationships: dict[str, dict[str, tuple[str, str, bool]]] = {}
    for name in sorted(parts):
        if not name.endswith(".rels"):
            continue
        folder, leaf = posixpath.split(name)
        _require(posixpath.basename(folder) == "_rels", f"Malformed relationship part path: {name}")
        owner = posixpath.join(posixpath.dirname(folder), leaf[:-5])
        if name == "_rels/.rels":
            owner = ""
        _require(not owner or owner in parts, f"Orphan relationship part: {name}, owner {owner}")
        root = xml(name)
        _require(root.tag == f"{{{PACKAGE_REL}}}Relationships", f"Invalid relationship root: {name}")
        by_id: dict[str, tuple[str, str, bool]] = {}
        for relation in root:
            _require(relation.tag == f"{{{PACKAGE_REL}}}Relationship", f"Malformed relationship element: {name}")
            rid, target, kind = (relation.get(key, "") for key in ("Id", "Target", "Type"))
            _require(bool(rid and target and kind), f"Missing relationship Id/Target/Type: {name}")
            _require(rid not in by_id, f"Duplicate relationship Id {rid}: {name}")
            mode = relation.get("TargetMode", "Internal")
            _require(mode in {"Internal", "External"}, f"Invalid relationship TargetMode: {name} {rid}")
            external = mode == "External"
            if not external:
                _require("\\" not in target, f"Invalid relationship target: {name} {target}")
                target = posixpath.normpath(target.lstrip("/") if target.startswith("/") else
                                           posixpath.join(posixpath.dirname(owner), target))
                _require(not target.startswith("../") and target in parts,
                         f"Missing or invalid relationship target: {name} {target}")
            by_id[rid] = kind, target, external
        relationships[owner] = by_id

    root_links = relationships.get("", {})
    workbook_links = [value for value in root_links.values() if value[0] == f"{REL}/officeDocument"]
    _require(workbook_links == [(f"{REL}/officeDocument", "xl/workbook.xml", False)],
             "Package must own exactly one internal xl/workbook.xml relationship")
    workbook = xml("xl/workbook.xml")
    _require(workbook.tag == f"{{{MAIN}}}workbook", "Invalid workbook XML root")
    workbook_rels = relationships.get("xl/workbook.xml", {})
    shared_strings: list[str] = []
    if "xl/sharedStrings.xml" in parts:
        shared_strings = ["".join(text.text or "" for text in item.findall(".//s:t", NS))
                          for item in xml("xl/sharedStrings.xml").findall("s:si", NS)]

    sheet_names: set[str] = set()
    sheet_ids: set[int] = set()
    worksheet_targets: set[str] = set()
    used_workbook_rids: set[str] = set()
    table_ids: set[int] = set()
    table_names: dict[str, str] = {}
    owned_tables: Counter[str] = Counter()
    sheet_rows: dict[str, int] = {}
    for sheet in workbook.findall("s:sheets/s:sheet", NS):
        title = sheet.get("name", "")
        _require(bool(title.strip()) and title.casefold() not in sheet_names,
                 f"Blank or duplicate worksheet name: {title!r}")
        sheet_names.add(title.casefold())
        sheet_id = _integer(sheet.get("sheetId"), f"{title} sheetId")
        _require(sheet_id not in sheet_ids, f"Duplicate sheetId: {sheet_id}")
        sheet_ids.add(sheet_id)
        rid = sheet.get(f"{{{REL}}}id", "")
        _require(rid in workbook_rels and rid not in used_workbook_rids,
                 f"Missing or duplicate workbook worksheet relationship: {title} {rid}")
        used_workbook_rids.add(rid)
        kind, target, external = workbook_rels[rid]
        _require(kind == f"{REL}/worksheet" and not external,
                 f"Invalid workbook worksheet relationship: {title} {rid}")
        _require(target not in worksheet_targets, f"Multiple owners for worksheet: {target}")
        worksheet_targets.add(target)
        worksheet = xml(target)
        _require(worksheet.tag == f"{{{MAIN}}}worksheet", f"Invalid worksheet root: {target}")
        rows = worksheet.findall("s:sheetData/s:row", NS)
        sheet_rows[title] = max((_integer(row.get("r"), f"{title} row") for row in rows), default=1) - 1
        cells = {cell.get("r"): cell for cell in worksheet.findall("s:sheetData/s:row/s:c", NS)}
        own_rels = relationships.get(target, {})
        table_parts = worksheet.findall("s:tableParts", NS)
        _require(len(table_parts) <= 1, f"Duplicate tableParts element: {title}")
        entries = list(table_parts[0]) if table_parts else []
        if table_parts:
            _require(_integer(table_parts[0].get("count"), f"{title} tableParts count", 0) == len(entries),
                     f"tableParts count mismatch: {title}")
        table_rids: set[str] = set()
        table_ranges: list[tuple[int, int, int, int]] = []
        for entry in entries:
            _require(entry.tag == f"{{{MAIN}}}tablePart", f"Malformed tablePart element: {title}")
            rid = entry.get(f"{{{REL}}}id", "")
            _require(rid in own_rels and rid not in table_rids,
                     f"Missing or duplicate table relationship: {title} {rid}")
            table_rids.add(rid)
            kind, table_path, external = own_rels[rid]
            _require(kind == f"{REL}/table" and not external,
                     f"Invalid table relationship: {title} {rid}")
            owned_tables[table_path] += 1
            _require(owned_tables[table_path] == 1, f"Multiple owners for table: {table_path}")
            table = xml(table_path)
            _require(table.tag == f"{{{MAIN}}}table", f"Invalid table XML root: {table_path}")
            table_id = _integer(table.get("id"), f"{table_path} table id")
            _require(table_id not in table_ids, f"Duplicate table ID: {table_id}")
            table_ids.add(table_id)
            for attribute in ("name", "displayName"):
                name = table.get(attribute, "")
                _require(bool(name.strip()), f"Blank table {attribute}: {table_path}")
                previous = table_names.setdefault(name.casefold(), table_path)
                _require(previous == table_path, f"Duplicate table name/displayName: {name}")
            rectangle = _rectangle(table.get("ref"), table_path)
            _require(rectangle[3] > rectangle[1], f"Header-only or empty table: {table_path}")
            cell_positions = [_rectangle(address, f"{title} cell") for address in cells]
            _require(any(rectangle[0] <= position[0] <= rectangle[2]
                         and rectangle[1] < position[1] <= rectangle[3] for position in cell_positions),
                     f"Table range contains no serialized data cells: {table_path}")
            _require(table.get("headerRowCount", "1") == "1", f"Table requires one header row: {table_path}")
            _require(not any(_overlaps(rectangle, previous) for previous in table_ranges),
                     f"Overlapping tables on worksheet: {title}")
            table_ranges.append(rectangle)
            columns_element = table.find("s:tableColumns", NS)
            _require(columns_element is not None, f"Missing tableColumns: {table_path}")
            columns = list(columns_element)
            _require(_integer(columns_element.get("count"), f"{table_path} tableColumn count") == len(columns),
                     f"tableColumn count mismatch: {table_path}")
            _require(len(columns) == rectangle[2] - rectangle[0] + 1,
                     f"tableColumn count does not match table width: {table_path}")
            header_names: set[str] = set()
            column_ids: set[int] = set()
            for offset, column in enumerate(columns):
                _require(column.tag == f"{{{MAIN}}}tableColumn", f"Malformed tableColumn: {table_path}")
                column_id = _integer(column.get("id"), f"{table_path} tableColumn id")
                _require(column_id not in column_ids, f"Duplicate tableColumn ID: {table_path}")
                column_ids.add(column_id)
                header = column.get("name", "")
                _require(bool(header.strip()), f"Blank table header: {table_path}")
                _require(header.casefold() not in header_names, f"Duplicate table header: {table_path} {header!r}")
                header_names.add(header.casefold())
                address = _cell_ref(rectangle[0] + offset, rectangle[1])
                cell = cells.get(address)
                _require(cell is not None and cell.get("t") in {"inlineStr", "s", "str"}
                         and cell.find("s:f", NS) is None,
                         f"Table header is not a string cell: {title}!{address}")
                if cell.get("t") == "inlineStr":
                    actual = "".join(item.text or "" for item in cell.findall("s:is//s:t", NS))
                elif cell.get("t") == "s":
                    value = _integer(cell.findtext("s:v", namespaces=NS), f"{title}!{address} shared string index", 0)
                    _require(value < len(shared_strings), f"Invalid shared string index: {title}!{address}")
                    actual = shared_strings[value]
                else:
                    actual = cell.findtext("s:v", default="", namespaces=NS)
                _require(actual == header, f"Table header/cell mismatch: {title}!{address}: {header!r} != {actual!r}")
            filters = table.findall("s:autoFilter", NS)
            _require(len(filters) == 1, f"Table must own exactly one AutoFilter: {table_path}")
            _require(_rectangle(filters[0].get("ref"), f"{table_path} AutoFilter") == rectangle,
                     f"Table AutoFilter ref mismatch: {table_path}")
        _require(table_rids == {rid for rid, value in own_rels.items() if value[0] == f"{REL}/table"},
                 f"Orphan table relationship: {title}")
        worksheet_filters = worksheet.findall("s:autoFilter", NS)
        _require(len(worksheet_filters) <= 1, f"Duplicate worksheet AutoFilter: {title}")
        for auto_filter in worksheet_filters:
            rectangle = _rectangle(auto_filter.get("ref"), f"{title} worksheet AutoFilter")
            _require(not any(_overlaps(rectangle, table_range) for table_range in table_ranges),
                     f"Worksheet AutoFilter overlaps Excel Table: {title}")

    actual_worksheets = {name for name in parts if name.startswith("xl/worksheets/") and name.endswith(".xml")}
    _require(worksheet_targets == actual_worksheets, "Orphan worksheet part or invalid worksheet ownership")
    _require(used_workbook_rids == {rid for rid, value in workbook_rels.items() if value[0] == f"{REL}/worksheet"},
             "Orphan workbook worksheet relationship")
    actual_tables = {name for name in parts if name.startswith("xl/tables/") and name.endswith(".xml")}
    _require(set(owned_tables) == actual_tables, "Orphan table part or invalid table ownership")
    _require(bool(sheet_rows), "Workbook has no worksheets")
    return {"path": str(path), "zip_crc_ok": True, "sheet_count": len(sheet_rows),
            "table_count": len(owned_tables), "sheet_rows": sheet_rows}

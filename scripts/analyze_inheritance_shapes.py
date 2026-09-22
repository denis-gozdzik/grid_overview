"""Summarize inheritance response shapes per archived page without printing values.

Usage:
    python scripts/analyze_inheritance_shapes.py output/run/raw
    python scripts/analyze_inheritance_shapes.py output/run/raw --object-type network

The script is offline-only. It reads immutable RAW archives and reports counts
of wrapper/plain/absent field shapes per effective-query page.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any


DEFAULT_FIELDS = ("options", "nextserver", "bootserver", "bootfile", "enable_ddns")


def _is_wrapper(value: Any) -> bool:
    return isinstance(value, dict) and ("inherited" in value or "multisource" in value)


def _classify(value_present: bool, value: Any) -> str:
    if not value_present:
        return "absent"
    if _is_wrapper(value):
        return "wrapper"
    if isinstance(value, list):
        if value and all(_is_wrapper(item) for item in value if isinstance(item, dict))                 and all(isinstance(item, dict) for item in value):
            return "wrapper"
        return "plain"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return "plain"
    return "other"


def _archive_root(path: Path) -> Path:
    if (path / "raw").is_dir():
        return path / "raw"
    return path


def _manifests(root: Path) -> list[Path]:
    if (root / "manifest.json").is_file():
        return [root / "manifest.json"]
    return sorted(root.glob("*/manifest.json"))


def _read_page(grid_dir: Path, relative: str) -> list[dict[str, Any]]:
    page_path = (grid_dir / relative).resolve()
    if not page_path.is_relative_to(grid_dir.resolve()):
        raise ValueError("Archive page path escapes Grid directory")
    payload = json.loads(page_path.read_text(encoding="utf-8"))
    rows = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"Invalid archived page: {relative}")
    return rows


def analyze(raw_dir: str | Path, object_type: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    root = _archive_root(Path(raw_dir))
    output: list[dict[str, Any]] = []
    for manifest_path in _manifests(root):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        grid = str(manifest.get("grid", manifest_path.parent.name))
        queries = [
            query for query in manifest.get("queries", [])
            if query.get("object_type") == object_type and query.get("mode") == "effective"
        ]
        for query in queries:
            for number, relative in enumerate(query.get("pages", []), start=1):
                rows = _read_page(manifest_path.parent, relative)
                counts = {field: Counter() for field in fields}
                for row in rows:
                    for field in fields:
                        counts[field][_classify(field in row, row.get(field))] += 1
                item: dict[str, Any] = {
                    "Grid": grid,
                    "Object": object_type,
                    "Page": number,
                    "Records": len(rows),
                    "Query Status": query.get("status", ""),
                }
                for field in fields:
                    for state in ("wrapper", "plain", "absent", "other"):
                        item[f"{field}.{state}"] = counts[field][state]
                output.append(item)
    return output


def _print(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    if not rows:
        print("No matching effective-query pages found.")
        return
    headers = ["Grid", "Object", "Page", "Records", "Query Status"]
    for field in fields:
        headers.extend([f"{field}.wrapper", f"{field}.plain", f"{field}.absent", f"{field}.other"])
    widths = {header: max(len(header), *(len(str(row.get(header, ""))) for row in rows)) for header in headers}
    print("  ".join(header.ljust(widths[header]) for header in headers))
    print("  ".join("-" * widths[header] for header in headers))
    for row in rows:
        print("  ".join(str(row.get(header, "")).ljust(widths[header]) for header in headers))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline inheritance-shape diagnostics; prints counts only, never field values."
    )
    parser.add_argument("raw_dir", help="Run directory, raw directory, or one Grid archive")
    parser.add_argument("--object-type", default="network")
    parser.add_argument("--fields", default=",".join(DEFAULT_FIELDS),
                        help="Comma-separated fields to classify")
    args = parser.parse_args()
    fields = tuple(dict.fromkeys(field.strip() for field in args.fields.split(",") if field.strip()))
    if not fields:
        parser.error("At least one field is required")
    rows = analyze(args.raw_dir, args.object_type, fields)
    _print(rows, fields)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

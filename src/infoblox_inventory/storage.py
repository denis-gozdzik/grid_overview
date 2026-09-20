"""Immutable decoded WAPI responses and offline reconstruction.

Pages are saved before normalization. The manifest contains query/coverage metadata,
never credentials. An existing Grid directory is refused to avoid mixing runs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .models import CollectionResult


FORMAT_VERSION = 1


def path_component(value: str) -> str:
    encoded = quote(value, safe="-_").replace(".", "%2E")
    if not encoded:
        raise ValueError("Empty archive path component")
    if encoded.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                           *(f"LPT{i}" for i in range(1, 10))}:
        encoded = f"%{ord(encoded[0]):02X}" + encoded[1:]
    return encoded


def page_records(page: Any) -> list[dict[str, Any]]:
    if not isinstance(page, dict) or "Error" in page:
        raise ValueError("Archived WAPI page is not a successful paging envelope")
    if "next_page_id" in page and (not isinstance(page["next_page_id"], str) or not page["next_page_id"]):
        raise ValueError("Archived WAPI page has an invalid continuation token")
    rows = page.get("result")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Archived WAPI page has no valid object list")
    return rows


class RawStore:
    def __init__(self, raw_dir: str | Path, result: CollectionResult):
        self.path = Path(raw_dir) / path_component(result.grid)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.mkdir()
        except FileExistsError:
            raise ValueError("Raw Grid directory already exists; select a fresh --output-dir") from None
        self.queries: list[dict[str, Any]] = []
        self.schema_paths: dict[str, str] = {}
        self.result = result
        self.finished = False
        self.save_manifest()

    def _write_new(self, relative: str, value: Any) -> None:
        destination = self.path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")

    def save_schema(self, object_type: str | None, schema: dict[str, Any]) -> None:
        key = object_type or "root"
        relative = f"schema/{path_component(key)}.json"
        self._write_new(relative, schema)
        self.schema_paths[key] = relative
        self.save_manifest()

    def start_query(self, object_type: str, mode: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {"object_type": object_type, "mode": mode, "params": params,
                 "status": "PARTIAL", "pages": [], "record_count": 0}
        self.queries.append(query)
        self.save_manifest()
        return query

    def save_page(self, query: dict[str, Any], page_number: int, page: Any) -> None:
        relative = (f"{path_component(query['object_type'])}/{query['mode']}/"
                    f"page-{page_number:06d}.json")
        self._write_new(relative, page)
        query["pages"].append(relative)
        try:
            query["record_count"] += len(page_records(page))
        except ValueError:
            query["status"] = "ERROR"
        self.save_manifest()

    def finish_query(self, query: dict[str, Any], status: str) -> None:
        query["status"] = status
        self.save_manifest()

    def finish_collection(self) -> None:
        self.finished = True
        self.save_manifest()

    def save_manifest(self) -> None:
        manifest = {"format_version": FORMAT_VERSION, "collection_finished": self.finished,
                    "grid": self.result.grid,
                    "grid_url": self.result.grid_url, "wapi_version": self.result.wapi_version,
                    "collected_at": self.result.collected_at, "schemas": self.schema_paths,
                    "queries": self.queries, "coverage": self.result.coverage,
                    "errors": self.result.errors}
        temporary = self.path / "manifest.json.tmp"
        temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path / "manifest.json")


def _read_relative(base: Path, relative: str) -> Any:
    if not isinstance(relative, str) or not relative:
        raise ValueError("Archive file path must be nonempty text")
    destination = (base / relative).resolve()
    if not destination.is_relative_to(base.resolve()):
        raise ValueError("Archive path escapes its Grid directory")
    return json.loads(destination.read_text(encoding="utf-8"))


def _validate_manifest(manifest: Any) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("Raw archive manifest must be a JSON object")
    if type(manifest.get("format_version")) is not int or manifest["format_version"] != FORMAT_VERSION:
        raise ValueError("Unsupported raw archive format version")
    for key in ("grid", "grid_url", "wapi_version", "collected_at"):
        if not isinstance(manifest.get(key), str):
            raise ValueError(f"Raw archive manifest requires text metadata: {key}")
    if not isinstance(manifest.get("collection_finished", False), bool):
        raise ValueError("Raw archive manifest has an invalid completion flag")
    for key in ("queries", "coverage", "errors"):
        if not isinstance(manifest.get(key), list) or any(not isinstance(row, dict) for row in manifest[key]):
            raise ValueError(f"Raw archive manifest requires an object list: {key}")
    if not isinstance(manifest.get("schemas"), dict):
        raise ValueError("Raw archive manifest requires a schema path mapping")
    seen: set[tuple[str, str]] = set()
    for query in manifest["queries"]:
        if not isinstance(query.get("object_type"), str) or not query["object_type"]:
            raise ValueError("Archived query requires an object type")
        if query.get("mode") not in ("raw", "effective"):
            raise ValueError("Unsupported raw archive query mode")
        if query.get("status") not in ("COMPLETE", "EMPTY", "PARTIAL", "ERROR"):
            raise ValueError("Archived query has an invalid status")
        if not isinstance(query.get("pages"), list) or any(not isinstance(page, str) for page in query["pages"]):
            raise ValueError("Archived query requires a list of page paths")
        identity = (query["object_type"], query["mode"])
        if identity in seen or len(query["pages"]) != len(set(query["pages"])):
            raise ValueError("Raw archive contains a duplicate query or page")
        seen.add(identity)


def load_raw(raw_dir: str | Path, selected_grid: str | None = None) -> list[CollectionResult]:
    """Load a run directory, its raw directory, or one Grid archive without networking."""
    root = Path(raw_dir)
    if (root / "raw").is_dir():
        root = root / "raw"
    manifests = [root / "manifest.json"] if (root / "manifest.json").is_file() else sorted(root.glob("*/manifest.json"))
    results: list[CollectionResult] = []
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        _validate_manifest(manifest)
        if selected_grid and manifest["grid"] != selected_grid:
            continue
        result = CollectionResult(manifest["grid"], grid_url=manifest["grid_url"],
                                  wapi_version=manifest["wapi_version"], collected_at=manifest["collected_at"],
                                  coverage=manifest["coverage"], errors=manifest["errors"])
        if not manifest.get("collection_finished", False):
            result.coverage.append({"Grid": result.grid, "Area": "Collection run", "Object": "",
                                    "Query": "", "Collection Status": "PARTIAL", "Objects Found": "",
                                    "Notes": "Collection was interrupted before completion"})
            result.errors.append({"grid": result.grid, "area": "Collection run", "object_type": "",
                                  "error": "Collection was interrupted before completion"})
        for key, relative in manifest["schemas"].items():
            if key != "root":
                schema = _read_relative(path.parent, relative)
                if not isinstance(schema, dict) or not isinstance(schema.get("fields"), list):
                    raise ValueError("Archived object schema has no valid fields list")
                result.schemas[key] = schema
        for query in manifest["queries"]:
            mode = query["mode"]
            if mode not in {"raw", "effective"}:
                raise ValueError("Unsupported raw archive query mode")
            records = result.records if mode == "raw" else result.effective_records
            rows = records.setdefault(query["object_type"], [])
            for relative in query["pages"]:
                page = _read_relative(path.parent, relative)
                try:
                    rows.extend(page_records(page))
                except ValueError:
                    if query["status"] not in {"ERROR", "PARTIAL"}:
                        raise
            if query["status"] in {"ERROR", "PARTIAL"}:
                note = "Archived query did not complete; only valid saved pages are available"
                if not any(item.get("Object") == query["object_type"] and item.get("Query") == mode
                           and item.get("Collection Status") in {"ERROR", "PARTIAL"} for item in result.coverage):
                    result.coverage.append({"Grid": result.grid, "Area": "DHCP options and inheritance",
                                            "Object": query["object_type"], "Query": mode,
                                            "Collection Status": "PARTIAL", "Objects Found": len(rows), "Notes": note})
        results.append(result)
    if not results:
        raise ValueError("No matching raw Grid archives found (expected manifest.json)")
    return results

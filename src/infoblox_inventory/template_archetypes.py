"""Human-facing template archetype catalog.

This layer intentionally groups exact bundle variants into coarse provisioning
archetypes. Exact hashes remain technical evidence; archetypes answer which
construction patterns exist across Grids.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from typing import Any

ARCHETYPE_SCHEMA_VERSION = 1
ARCHETYPE_HASH_LENGTH = 10

TEMPLATE_ARCHETYPE_HEADERS = [
    "Archetype ID", "Archetype", "Structure", "Provisioning Family",
    "Association Mode", "Instance Count", "Grid Count", "Grid Coverage %",
    "Commonality", "Variant Count", "Grids", "Prefixes", "Options States",
    "Network Templates", "Range Templates",
]

TEMPLATE_VARIANT_HEADERS = [
    "Archetype ID", "Archetype", "Variant ID", "Variant Signature",
    "Instance Count", "Grid Count", "Grid Coverage %", "Grids", "Prefixes",
    "Range Pattern", "Options States", "Network Templates", "Range Templates",
]

TEMPLATE_INSTANCE_HEADERS = [
    "Grid", "Archetype ID", "Archetype", "Variant ID",
    "Network Template", "Range Template", "Prefix", "Provisioning Family",
    "Association Mode", "Range Start", "Range End", "Exclusion Pattern",
    "Options State",
]

TEMPLATE_GRID_MAP_HEADERS = [
    "Grid", "Archetype ID", "Archetype", "Instances", "Variants", "Prefixes",
    "Options States", "Network Templates", "Range Templates",
]

TEMPLATE_REVIEW_HEADERS = [
    "Grid", "Issue", "Bundle Status", "Provisioning Family",
    "Network Template", "Range Template", "Prefix", "Association Mode",
    "Review Flags", "Notes",
]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _archetype_structure(row: dict[str, Any]) -> str:
    status = str(row.get("Bundle Status") or "")
    if status == "LINKED":
        return "NETWORK + RANGE"
    if status == "NETWORK_ONLY":
        return "NETWORK ONLY"
    return status or "UNKNOWN"


def _archetype_key(row: dict[str, Any]) -> dict[str, Any]:
    structure = _archetype_structure(row)
    family = str(row.get("Provisioning Family") or "UNKNOWN")
    association = str(row.get("Range Association") or "") if structure == "NETWORK + RANGE" else ""
    fixed = bool(str(row.get("Fixed Address Templates") or "").strip())
    return {
        "schema_version": ARCHETYPE_SCHEMA_VERSION,
        "structure": structure,
        "provisioning_family": family,
        "association_mode": association,
        "has_fixed_address_templates": fixed,
    }


def _archetype_id(key: dict[str, Any]) -> str:
    digest = sha256(_json(key).encode("utf-8")).hexdigest()
    return f"ARCH{ARCHETYPE_SCHEMA_VERSION}-{digest[:ARCHETYPE_HASH_LENGTH]}"


def _family_label(family: str) -> str:
    if family == "MS_SERVER":
        return "Microsoft DHCP"
    if family in {"INFOBLOX", "INFOBLOX_MEMBER"}:
        return "Infoblox DHCP"
    if family == "NETWORK_ONLY":
        return "Network only"
    return family.replace("_", " ").title() if family else "Unknown"


def _archetype_name(key: dict[str, Any]) -> str:
    family = str(key["provisioning_family"])
    structure = str(key["structure"])
    association = str(key.get("association_mode") or "")
    fixed = bool(key.get("has_fixed_address_templates"))

    name = f"{_family_label(family)} — {structure.title()}"
    if structure == "NETWORK + RANGE" and association and association not in {"MS_SERVER", "NONE"}:
        name += f" ({association})"
    if fixed:
        name += " + Fixed Address Template"
    return name


def _commonality(grid_count: int, total_grids: int) -> str:
    if total_grids and grid_count == total_grids:
        return "ALL_COLLECTED_GRIDS"
    if grid_count > 1:
        return "MULTI_GRID"
    return "GRID_SPECIFIC"


def _review_issue(row: dict[str, Any]) -> str:
    status = str(row.get("Bundle Status") or "")
    if status == "ORPHAN_RANGE_TEMPLATE":
        return "ORPHAN_RANGE_TEMPLATE"
    if status == "MISSING_RANGE_TEMPLATE":
        return "MISSING_RANGE_TEMPLATE"
    flags = str(row.get("Review Flags") or "").strip()
    if flags:
        return flags
    return "REVIEW_REQUIRED"


def build_template_archetype_catalog(
    bundle_rows: list[dict[str, Any]],
    bundle_models: list[dict[str, Any]],
    grids: list[str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Return archetypes, variants, instances, per-Grid map and review backlog."""
    total_grids = len(set(grids))
    model_index = {
        str(row.get("Bundle Model ID") or ""): row
        for row in bundle_models
    }

    valid_rows = [
        row for row in bundle_rows
        if str(row.get("Attention") or "") == "OK"
        and str(row.get("Bundle Status") or "") in {"LINKED", "NETWORK_ONLY"}
    ]
    review_rows = [
        {
            "Grid": row.get("Grid"),
            "Issue": _review_issue(row),
            "Bundle Status": row.get("Bundle Status"),
            "Provisioning Family": row.get("Provisioning Family"),
            "Network Template": row.get("Network Template"),
            "Range Template": row.get("Range Template"),
            "Prefix": row.get("Network Prefix"),
            "Association Mode": row.get("Range Association"),
            "Review Flags": row.get("Review Flags"),
            "Notes": row.get("Notes"),
        }
        for row in bundle_rows
        if row not in valid_rows
    ]

    annotated: list[dict[str, Any]] = []
    for row in valid_rows:
        key = _archetype_key(row)
        archetype_id = _archetype_id(key)
        annotated.append({
            **row,
            "_archetype_id": archetype_id,
            "_archetype_name": _archetype_name(key),
            "_archetype_key": key,
        })

    archetype_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in annotated:
        archetype_groups[str(row["_archetype_id"])].append(row)

    archetypes: list[dict[str, Any]] = []
    for archetype_id, rows in sorted(archetype_groups.items()):
        key = rows[0]["_archetype_key"]
        model_grids = sorted({str(row.get("Grid") or "") for row in rows if row.get("Grid")})
        variants = sorted({str(row.get("Bundle Model ID") or "") for row in rows if row.get("Bundle Model ID")})
        prefixes = sorted({str(row.get("Network Prefix") or "") for row in rows if row.get("Network Prefix")})
        option_states = sorted({str(row.get("Options State") or "") for row in rows if row.get("Options State")})
        archetypes.append({
            "Archetype ID": archetype_id,
            "Archetype": rows[0]["_archetype_name"],
            "Structure": key["structure"],
            "Provisioning Family": key["provisioning_family"],
            "Association Mode": key["association_mode"],
            "Instance Count": len(rows),
            "Grid Count": len(model_grids),
            "Grid Coverage %": round(len(model_grids) * 100.0 / total_grids, 1) if total_grids else None,
            "Commonality": _commonality(len(model_grids), total_grids),
            "Variant Count": len(variants),
            "Grids": ", ".join(model_grids),
            "Prefixes": ", ".join(prefixes),
            "Options States": ", ".join(option_states),
            "Network Templates": ", ".join(sorted({str(row.get("Network Template") or "") for row in rows if row.get("Network Template")})),
            "Range Templates": ", ".join(sorted({str(row.get("Range Template") or "") for row in rows if row.get("Range Template")})),
        })

    variant_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in annotated:
        variant_groups[(str(row["_archetype_id"]), str(row.get("Bundle Model ID") or ""))].append(row)

    variants: list[dict[str, Any]] = []
    for (archetype_id, variant_id), rows in sorted(variant_groups.items()):
        model = model_index.get(variant_id, {})
        model_grids = sorted({str(row.get("Grid") or "") for row in rows if row.get("Grid")})
        variants.append({
            "Archetype ID": archetype_id,
            "Archetype": rows[0]["_archetype_name"],
            "Variant ID": variant_id,
            "Variant Signature": model.get("Model Signature") or variant_id,
            "Instance Count": len(rows),
            "Grid Count": len(model_grids),
            "Grid Coverage %": round(len(model_grids) * 100.0 / total_grids, 1) if total_grids else None,
            "Grids": ", ".join(model_grids),
            "Prefixes": ", ".join(sorted({str(row.get("Network Prefix") or "") for row in rows if row.get("Network Prefix")})),
            "Range Pattern": model.get("Pattern Summary") or "",
            "Options States": ", ".join(sorted({str(row.get("Options State") or "") for row in rows if row.get("Options State")})),
            "Network Templates": ", ".join(sorted({str(row.get("Network Template") or "") for row in rows if row.get("Network Template")})),
            "Range Templates": ", ".join(sorted({str(row.get("Range Template") or "") for row in rows if row.get("Range Template")})),
        })

    instances = [
        {
            "Grid": row.get("Grid"),
            "Archetype ID": row["_archetype_id"],
            "Archetype": row["_archetype_name"],
            "Variant ID": row.get("Bundle Model ID"),
            "Network Template": row.get("Network Template"),
            "Range Template": row.get("Range Template"),
            "Prefix": row.get("Network Prefix"),
            "Provisioning Family": row.get("Provisioning Family"),
            "Association Mode": row.get("Range Association"),
            "Range Start": row.get("Range Start"),
            "Range End": row.get("Range End"),
            "Exclusion Pattern": row.get("Exclusion Pattern"),
            "Options State": row.get("Options State"),
        }
        for row in annotated
    ]

    grid_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in annotated:
        grid_groups[(str(row.get("Grid") or ""), str(row["_archetype_id"]))].append(row)
    grid_map: list[dict[str, Any]] = []
    for (grid, archetype_id), rows in sorted(grid_groups.items()):
        grid_map.append({
            "Grid": grid,
            "Archetype ID": archetype_id,
            "Archetype": rows[0]["_archetype_name"],
            "Instances": len(rows),
            "Variants": len({str(row.get("Bundle Model ID") or "") for row in rows}),
            "Prefixes": ", ".join(sorted({str(row.get("Network Prefix") or "") for row in rows if row.get("Network Prefix")})),
            "Options States": ", ".join(sorted({str(row.get("Options State") or "") for row in rows if row.get("Options State")})),
            "Network Templates": ", ".join(sorted({str(row.get("Network Template") or "") for row in rows if row.get("Network Template")})),
            "Range Templates": ", ".join(sorted({str(row.get("Range Template") or "") for row in rows if row.get("Range Template")})),
        })

    return archetypes, variants, instances, grid_map, review_rows

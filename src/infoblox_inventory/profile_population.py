"""Profile-specific object population selection.

The current-state inventory contains many IPAM Network objects that may not
participate in DHCP.  Network DHCP profile discovery therefore uses a bounded,
evidence-based candidate population instead of treating every Network as a
DHCP-configured object.

This is a relevance classifier, not an assertion of appliance service state.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .models import CollectionResult


NETWORK_POPULATION_BASIS = "DHCP_RELEVANT_NETWORK_CANDIDATES"
RANGE_POPULATION_BASIS = "ALL_RANGES"

REASON_MEMBERS = "members"
REASON_RANGE_PARENT = "range_parent"
REASON_USE_FLAG = "active_use_flag"
REASON_ACTIVE_OPTION = "active_option"


def object_key(grid: str, row: dict[str, Any]) -> tuple[str, str]:
    """Stable in-memory identity for raw/effective inventory rows."""
    ref = row.get("_ref")
    if isinstance(ref, str) and ref:
        return grid, ref
    fallback = [
        row.get("network_view") or "default",
        row.get("network") or "",
        row.get("start_addr") or "",
        row.get("end_addr") or "",
        row.get("ipv4addr") or "",
        row.get("name") or row.get("host_name") or "",
    ]
    return grid, "|".join(str(value) for value in fallback)


def normalized_object_key(row: dict[str, Any]) -> tuple[str, str]:
    """Match normalized evidence back to its source object without exposing values."""
    ref = row.get("object_ref")
    if isinstance(ref, str) and ref:
        return str(row.get("grid", "")), ref
    return str(row.get("grid", "")), "|".join(str(value or "") for value in (
        row.get("network_view") or "default",
        row.get("parent_network") or "",
        "",
        "",
        "",
        row.get("object_name") or "",
    ))


def _active_option(record: dict[str, Any]) -> bool:
    options = record.get("options")
    return isinstance(options, list) and any(
        isinstance(option, dict) and option.get("use_option") is True
        for option in options
    )


def _active_use_flag(record: dict[str, Any]) -> bool:
    return any(
        isinstance(name, str) and name.startswith("use_") and value is True
        for name, value in record.items()
    )


def dhcp_relevant_networks(results: list[CollectionResult]) -> dict[tuple[str, str], set[str]]:
    """Return evidence-backed Network candidates and the reasons each was selected."""
    relevant: dict[tuple[str, str], set[str]] = {}
    for result in results:
        parents = {
            (str(row.get("network_view") or "default"), str(row.get("network") or ""))
            for row in result.records.get("range", [])
            if row.get("network")
        }
        for record in result.records.get("network", []):
            reasons: set[str] = set()
            if record.get("members"):
                reasons.add(REASON_MEMBERS)
            if (str(record.get("network_view") or "default"), str(record.get("network") or "")) in parents:
                reasons.add(REASON_RANGE_PARENT)
            if _active_use_flag(record):
                reasons.add(REASON_USE_FLAG)
            if _active_option(record):
                reasons.add(REASON_ACTIVE_OPTION)
            if reasons:
                relevant[object_key(result.grid, record)] = reasons
    return relevant


def effective_network_keys(results: list[CollectionResult]) -> set[tuple[str, str]]:
    return {
        object_key(result.grid, record)
        for result in results
        for record in result.effective_records.get("network", [])
    }


def all_range_keys(results: list[CollectionResult]) -> set[tuple[str, str]]:
    return {
        object_key(result.grid, record)
        for result in results
        for record in result.records.get("range", [])
    }


def effective_range_keys(results: list[CollectionResult]) -> set[tuple[str, str]]:
    return {
        object_key(result.grid, record)
        for result in results
        for record in result.effective_records.get("range", [])
    }


def effective_records_by_key(results: list[CollectionResult], object_type: str) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        object_key(result.grid, record): record
        for result in results
        for record in result.effective_records.get(object_type, [])
    }


def profile_population_summary(results: list[CollectionResult]) -> list[dict[str, Any]]:
    """Summarize candidate selection without exposing addresses or names."""
    relevant = dhcp_relevant_networks(results)
    rows: list[dict[str, Any]] = []
    totals = Counter()
    for result in results:
        grid_keys = {
            object_key(result.grid, row)
            for row in result.records.get("network", [])
        }
        selected = {key: relevant[key] for key in grid_keys if key in relevant}
        counts = Counter(reason for reasons in selected.values() for reason in reasons)
        total = len(grid_keys)
        candidate = len(selected)
        row = {
            "Grid": result.grid,
            "All Networks": total,
            "DHCP-Relevant Candidates": candidate,
            "Candidate %": round(candidate * 100.0 / total, 1) if total else None,
            "With Members": counts[REASON_MEMBERS],
            "Parent of Range": counts[REASON_RANGE_PARENT],
            "Active use_* flag": counts[REASON_USE_FLAG],
            "Active DHCP option": counts[REASON_ACTIVE_OPTION],
        }
        rows.append(row)
        totals.update({
            "All Networks": total,
            "DHCP-Relevant Candidates": candidate,
            "With Members": counts[REASON_MEMBERS],
            "Parent of Range": counts[REASON_RANGE_PARENT],
            "Active use_* flag": counts[REASON_USE_FLAG],
            "Active DHCP option": counts[REASON_ACTIVE_OPTION],
        })
    total = totals["All Networks"]
    candidate = totals["DHCP-Relevant Candidates"]
    rows.append({
        "Grid": "ALL",
        "All Networks": total,
        "DHCP-Relevant Candidates": candidate,
        "Candidate %": round(candidate * 100.0 / total, 1) if total else None,
        "With Members": totals["With Members"],
        "Parent of Range": totals["Parent of Range"],
        "Active use_* flag": totals["Active use_* flag"],
        "Active DHCP option": totals["Active DHCP option"],
    })
    return rows

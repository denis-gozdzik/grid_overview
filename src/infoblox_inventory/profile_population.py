"""Profile-specific population selection and descriptive segmentation.

Population logic is evidence-backed and deliberately separate from standards:
it identifies which objects are applicable to future profile discovery, not
whether any object is compliant or correctly configured.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .models import CollectionResult


NETWORK_POPULATION_BASIS = "DHCP_RELEVANT_NETWORK_CANDIDATES"
RANGE_POPULATION_BASIS = "ALL_RANGES"
RANGE_DHCP_ASSOCIATED_BASIS = "DHCP_ASSOCIATED_RANGES"
RANGE_INFOBLOX_MANAGED_BASIS = "INFOBLOX_MANAGED_RANGES"

RANGE_SEGMENT_MS_SERVER = "MS_SERVER"
RANGE_SEGMENT_MEMBER = "MEMBER"
RANGE_SEGMENT_FAILOVER = "FAILOVER"
RANGE_SEGMENT_NONE = "NONE"
RANGE_SEGMENT_OTHER = "OTHER"
RANGE_SEGMENT_UNKNOWN = "UNKNOWN"
RANGE_SEGMENTS = (
    RANGE_SEGMENT_MS_SERVER,
    RANGE_SEGMENT_MEMBER,
    RANGE_SEGMENT_FAILOVER,
    RANGE_SEGMENT_NONE,
    RANGE_SEGMENT_OTHER,
    RANGE_SEGMENT_UNKNOWN,
)

REASON_MEMBERS = "members"
REASON_RANGE_PARENT = "range_parent"
REASON_USE_FLAG = "active_use_flag"
REASON_ACTIVE_OPTION = "active_option"

PROFILE_POPULATION_HEADERS = [
    "Profile", "Scope", "Grid", "Population Basis", "Segment",
    "Object Count", "Share %", "Observed Association Values", "Notes",
]


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


def range_association_segment(record: dict[str, Any]) -> tuple[str, str]:
    """Classify RAW Range association without inventing management semantics.

    The normalized segment drives applicability. The second element preserves
    the original non-empty value for descriptive evidence when it is unknown.
    """
    value = record.get("server_association_type")
    if value is None:
        return RANGE_SEGMENT_NONE, ""
    if not isinstance(value, (str, int, float, bool)):
        return RANGE_SEGMENT_UNKNOWN, repr(value)
    raw = str(value).strip()
    if not raw:
        return RANGE_SEGMENT_NONE, ""
    normalized = raw.upper().replace("-", "_").replace(" ", "_")
    if normalized in {"NONE", "NOT_CONFIGURED"}:
        return RANGE_SEGMENT_NONE, raw
    if normalized == "MEMBER":
        return RANGE_SEGMENT_MEMBER, raw
    if normalized in {"MS_SERVER", "MSSERVER"}:
        return RANGE_SEGMENT_MS_SERVER, raw
    if normalized in {"FAILOVER", "FAILOVER_ASSOCIATION"}:
        return RANGE_SEGMENT_FAILOVER, raw
    return RANGE_SEGMENT_OTHER, raw


def range_segments(results: list[CollectionResult]) -> dict[str, set[tuple[str, str]]]:
    segments = {name: set() for name in RANGE_SEGMENTS}
    for result in results:
        for record in result.records.get("range", []):
            segment, _raw = range_association_segment(record)
            segments[segment].add(object_key(result.grid, record))
    return segments


def dhcp_associated_range_keys(results: list[CollectionResult]) -> set[tuple[str, str]]:
    segments = range_segments(results)
    return set().union(
        segments[RANGE_SEGMENT_MEMBER],
        segments[RANGE_SEGMENT_FAILOVER],
        segments[RANGE_SEGMENT_MS_SERVER],
    )


def infoblox_managed_range_keys(results: list[CollectionResult]) -> set[tuple[str, str]]:
    segments = range_segments(results)
    return set().union(
        segments[RANGE_SEGMENT_MEMBER],
        segments[RANGE_SEGMENT_FAILOVER],
    )


def ms_server_range_keys(results: list[CollectionResult]) -> set[tuple[str, str]]:
    return set(range_segments(results)[RANGE_SEGMENT_MS_SERVER])


def profile_population_summary(results: list[CollectionResult]) -> list[dict[str, Any]]:
    """Backward-compatible compact Network population summary."""
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


def profile_population_rows(results: list[CollectionResult]) -> list[dict[str, Any]]:
    """Long-form descriptive population evidence for Network and Range profiles."""
    relevant_networks = dhcp_relevant_networks(results)
    rows: list[dict[str, Any]] = []

    for result in results:
        network_keys = {
            object_key(result.grid, record)
            for record in result.records.get("network", [])
        }
        network_candidates = network_keys & set(relevant_networks)
        network_total = len(network_keys)
        rows.extend([
            {
                "Profile": "Network Profile v1", "Scope": "Network", "Grid": result.grid,
                "Population Basis": "ALL_NETWORKS", "Segment": "ALL",
                "Object Count": network_total, "Share %": 100.0 if network_total else None,
                "Observed Association Values": "",
                "Notes": "All IPAM Network objects; descriptive source population.",
            },
            {
                "Profile": "Network Profile v1", "Scope": "Network", "Grid": result.grid,
                "Population Basis": NETWORK_POPULATION_BASIS, "Segment": "CANDIDATE",
                "Object Count": len(network_candidates),
                "Share %": round(len(network_candidates) * 100.0 / network_total, 1) if network_total else None,
                "Observed Association Values": "",
                "Notes": "Evidence-backed DHCP-relevant candidates; not a compliance classification.",
            },
        ])

        range_records = result.records.get("range", [])
        range_total = len(range_records)
        segment_counts: Counter[str] = Counter()
        observed: dict[str, set[str]] = defaultdict(set)
        for record in range_records:
            segment, raw = range_association_segment(record)
            segment_counts[segment] += 1
            if raw:
                observed[segment].add(raw)
        associated = (
            segment_counts[RANGE_SEGMENT_MEMBER]
            + segment_counts[RANGE_SEGMENT_FAILOVER]
            + segment_counts[RANGE_SEGMENT_MS_SERVER]
        )
        infoblox_managed = segment_counts[RANGE_SEGMENT_MEMBER] + segment_counts[RANGE_SEGMENT_FAILOVER]
        rows.extend([
            {
                "Profile": "Range Profile v1", "Scope": "Range", "Grid": result.grid,
                "Population Basis": RANGE_POPULATION_BASIS, "Segment": "ALL",
                "Object Count": range_total, "Share %": 100.0 if range_total else None,
                "Observed Association Values": "",
                "Notes": "All collected Range objects; descriptive source population.",
            },
            {
                "Profile": "Range Profile v1", "Scope": "Range", "Grid": result.grid,
                "Population Basis": RANGE_DHCP_ASSOCIATED_BASIS, "Segment": "ASSOCIATED",
                "Object Count": associated,
                "Share %": round(associated * 100.0 / range_total, 1) if range_total else None,
                "Observed Association Values": "",
                "Notes": "MEMBER + FAILOVER + MS_SERVER; used for effective DHCP option inputs.",
            },
            {
                "Profile": "Range Profile v1", "Scope": "Range", "Grid": result.grid,
                "Population Basis": RANGE_INFOBLOX_MANAGED_BASIS, "Segment": "INFOBLOX_MANAGED",
                "Object Count": infoblox_managed,
                "Share %": round(infoblox_managed * 100.0 / range_total, 1) if range_total else None,
                "Observed Association Values": "",
                "Notes": "MEMBER + FAILOVER; base population for Infoblox scalar inputs.",
            },
        ])
        for segment in RANGE_SEGMENTS:
            count = segment_counts[segment]
            rows.append({
                "Profile": "Range Profile v1", "Scope": "Range", "Grid": result.grid,
                "Population Basis": f"RANGE_SEGMENT_{segment}", "Segment": segment,
                "Object Count": count,
                "Share %": round(count * 100.0 / range_total, 1) if range_total else None,
                "Observed Association Values": ", ".join(sorted(observed[segment])),
                "Notes": (
                    "Externally managed by Microsoft DHCP; not equivalent to NOT_CONFIGURED."
                    if segment == RANGE_SEGMENT_MS_SERVER else
                    "No active server association observed."
                    if segment == RANGE_SEGMENT_NONE else
                    "Unexpected association value retained for manual review."
                    if segment in {RANGE_SEGMENT_OTHER, RANGE_SEGMENT_UNKNOWN} else
                    ""
                ),
            })
    return rows

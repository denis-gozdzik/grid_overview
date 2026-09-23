"""Descriptive context and parent Network↔Range profile relationships.

This layer explains where deterministic functional fingerprints occur. Context
never changes fingerprint identity and never infers semantic profile names,
standards, compliance, or remediation.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from typing import Any

from .models import CollectionResult
from .profile_population import object_key, normalized_object_key
from .profile_readiness import PROFILE_INPUT_SPECS, profile_parameter_rows


PROFILE_CONTEXT_HEADERS = [
    "Profile", "Fingerprint ID", "Scope", "Object Count",
    "Network View Distribution", "Association Family Distribution",
    "Network Relevance Reason Distribution", "EA Key Presence",
    "EA Top Values", "Comment Present Objects", "Comment Present %",
    "Core Source Signature Distribution",
]

PROFILE_RELATIONSHIP_HEADERS = [
    "Relationship Status", "Network Fingerprint ID", "Range Fingerprint ID",
    "Association Family", "Range Count", "Share of Associated Ranges %",
    "Share of Paired Profiled Ranges %", "Network View Distribution", "Notes",
]

PROFILE_RELATIONSHIP_ASSIGNMENT_HEADERS = [
    "Grid", "Network View", "Parent Network", "Parent Network Status",
    "Parent Network Fingerprint ID", "Range", "Association Family",
    "Range Status", "Range Fingerprint ID", "Relationship Status",
]

CORE_INPUT_KEYS = ("lease_time", "dns_servers", "domain_name", "gateway_convention")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _raw_records_by_ref(results: list[CollectionResult], object_type: str) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        object_key(result.grid, record): record
        for result in results
        for record in result.records.get(object_type, [])
    }


def _assignment_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("Grid", "")), str(row.get("Object Ref", ""))


def _distribution(values: list[str]) -> str:
    return _json(dict(sorted(Counter(values).items(), key=lambda item: (-item[1], item[0]))))


def _bounded_counter(counter: Counter[str], limit: int = 20) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit])


def _extattrs(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("extattrs")
    return value if isinstance(value, dict) else {}


def _ea_value(payload: Any) -> Any:
    if isinstance(payload, dict) and "value" in payload:
        return payload.get("value")
    return payload


def _source_signature_rows(scalars: list[dict[str, Any]], options: list[dict[str, Any]],
                           scope: str) -> dict[str, dict[tuple[str, str], list[dict[str, Any]]]]:
    grouped: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = {}
    for spec in PROFILE_INPUT_SPECS:
        if spec.scope != scope or spec.input_key not in CORE_INPUT_KEYS:
            continue
        by_object: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in profile_parameter_rows(spec, scalars, options):
            by_object[normalized_object_key(row)].append(row)
        grouped[spec.input_key] = by_object
    return grouped


def _source_signature(rows: list[dict[str, Any]]) -> str:
    if any(row.get("multisource") is True for row in rows):
        return "MULTISOURCE"
    relevant = [
        row for row in rows
        if row.get("status") in {"COMPLETE", "NOT_CONFIGURED"}
    ]
    levels = sorted({
        str(row.get("source_level") or "UNKNOWN")
        for row in relevant
    })
    if not levels:
        return "NO_NORMALIZED_SOURCE"
    return "+".join(levels)


def build_profile_context(results: list[CollectionResult], scalars: list[dict[str, Any]],
                          options: list[dict[str, Any]],
                          assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize bounded context for each resolved fingerprint."""
    raw_by_scope = {
        "Network": _raw_records_by_ref(results, "network"),
        "Range": _raw_records_by_ref(results, "range"),
    }
    output: list[dict[str, Any]] = []

    for scope in ("Network", "Range"):
        source_rows = _source_signature_rows(scalars, options, scope)
        profiled = [
            row for row in assignments
            if row.get("Scope") == scope and row.get("Population Status") == "PROFILED"
        ]
        by_fingerprint: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in profiled:
            by_fingerprint[str(row.get("Fingerprint ID"))].append(row)

        for fingerprint_id, rows in sorted(by_fingerprint.items(),
                                           key=lambda item: (-len(item[1]), item[0])):
            keys = [_assignment_key(row) for row in rows]
            raw_rows = [raw_by_scope[scope].get(key, {}) for key in keys]

            views = [str(row.get("Network View") or "") for row in rows]
            associations = [
                str(row.get("Association Family") or "")
                for row in rows if row.get("Association Family")
            ]

            relevance_counter: Counter[str] = Counter()
            for row in rows:
                for reason in str(row.get("Network Relevance Reasons") or "").split(","):
                    reason = reason.strip()
                    if reason:
                        relevance_counter[reason] += 1

            ea_key_counter: Counter[str] = Counter()
            ea_value_counters: dict[str, Counter[str]] = defaultdict(Counter)
            for record in raw_rows:
                for key, payload in _extattrs(record).items():
                    key_text = str(key)
                    ea_key_counter[key_text] += 1
                    value = _ea_value(payload)
                    ea_value_counters[key_text][_json(value)] += 1

            top_ea_keys = [key for key, _count in sorted(
                ea_key_counter.items(), key=lambda item: (-item[1], item[0])
            )[:20]]
            ea_values = {
                key: _bounded_counter(ea_value_counters[key], 5)
                for key in top_ea_keys
            }

            source_summary: dict[str, dict[str, int]] = {}
            for input_key in CORE_INPUT_KEYS:
                counter: Counter[str] = Counter()
                by_object = source_rows.get(input_key, {})
                for key in keys:
                    counter[_source_signature(by_object.get(key, []))] += 1
                source_summary[input_key] = _bounded_counter(counter, 20)

            comment_present = sum(bool(str(record.get("comment") or "").strip()) for record in raw_rows)
            count = len(rows)
            output.append({
                "Profile": f"{scope} Profile v1",
                "Fingerprint ID": fingerprint_id,
                "Scope": scope,
                "Object Count": count,
                "Network View Distribution": _distribution(views),
                "Association Family Distribution": _distribution(associations) if associations else "",
                "Network Relevance Reason Distribution": (
                    _json(_bounded_counter(relevance_counter, 20)) if relevance_counter else ""
                ),
                "EA Key Presence": _json(_bounded_counter(ea_key_counter, 20)) if ea_key_counter else "",
                "EA Top Values": _json(ea_values) if ea_values else "",
                "Comment Present Objects": comment_present,
                "Comment Present %": round(comment_present * 100.0 / count, 1) if count else None,
                "Core Source Signature Distribution": _json(source_summary),
            })
    return output


def _network_lookup(results: list[CollectionResult]) -> dict[tuple[str, str, str], tuple[str, str]]:
    lookup: dict[tuple[str, str, str], tuple[str, str]] = {}
    for result in results:
        for record in result.records.get("network", []):
            network = str(record.get("network") or "")
            if not network:
                continue
            view = str(record.get("network_view") or "default")
            identity = object_key(result.grid, record)
            key = (result.grid, view, network)
            if key in lookup and lookup[key] != identity:
                raise ValueError(f"Duplicate parent Network identity for {result.grid}/{view}/{network}")
            lookup[key] = identity
    return lookup


def build_profile_relationships(results: list[CollectionResult],
                                assignments: list[dict[str, Any]]) -> tuple[
                                    list[dict[str, Any]], list[dict[str, Any]]
                                ]:
    """Describe deterministic parent Network↔Range profile pairings."""
    assignment_by_key = {
        _assignment_key(row): row
        for row in assignments
    }
    network_lookup = _network_lookup(results)
    detail: list[dict[str, Any]] = []

    for result in results:
        for record in result.records.get("range", []):
            range_key = object_key(result.grid, record)
            range_assignment = assignment_by_key.get(range_key)
            range_status = str((range_assignment or {}).get("Population Status") or "NOT_IN_PROFILE_ASSIGNMENTS")
            association = str((range_assignment or {}).get("Association Family")
                              or record.get("server_association_type") or "")
            view = str(record.get("network_view") or "default")
            parent_network = str(record.get("network") or "")
            parent_key = network_lookup.get((result.grid, view, parent_network))
            parent_assignment = assignment_by_key.get(parent_key) if parent_key else None
            parent_status = str((parent_assignment or {}).get("Population Status") or "")

            if range_status == "NOT_APPLICABLE_TO_DHCP_PROFILE":
                relationship_status = "RANGE_NOT_APPLICABLE"
            elif range_status == "UNRESOLVED_ASSOCIATION":
                relationship_status = "RANGE_ASSOCIATION_UNRESOLVED"
            elif range_status == "UNRESOLVED_PROFILE_INPUTS":
                relationship_status = "RANGE_PROFILE_UNRESOLVED"
            elif range_status != "PROFILED":
                relationship_status = "RANGE_NOT_PROFILED"
            elif parent_key is None:
                relationship_status = "PARENT_NETWORK_NOT_FOUND"
            elif parent_assignment is None:
                relationship_status = "PARENT_NOT_PROFILE_CANDIDATE"
            elif parent_status == "PROFILED":
                relationship_status = "PROFILE_PAIR"
            elif parent_status == "UNRESOLVED_PROFILE_INPUTS":
                relationship_status = "PARENT_PROFILE_UNRESOLVED"
            else:
                relationship_status = "PARENT_NOT_PROFILED"

            detail.append({
                "Grid": result.grid,
                "Network View": view,
                "Parent Network": parent_network,
                "Parent Network Status": parent_status or ("NOT_FOUND" if parent_key is None else "NOT_PROFILE_CANDIDATE"),
                "Parent Network Fingerprint ID": (parent_assignment or {}).get("Fingerprint ID", ""),
                "Range": (
                    f"{record.get('start_addr')}-{record.get('end_addr')}"
                    if record.get("start_addr") and record.get("end_addr")
                    else str(record.get("_ref") or "")
                ),
                "Association Family": association,
                "Range Status": range_status,
                "Range Fingerprint ID": (range_assignment or {}).get("Fingerprint ID", ""),
                "Relationship Status": relationship_status,
            })

    associated = [
        row for row in detail
        if row["Range Status"] in {"PROFILED", "UNRESOLVED_PROFILE_INPUTS"}
    ]
    paired_profiled = [row for row in associated if row["Relationship Status"] == "PROFILE_PAIR"]
    associated_count = len(associated)
    paired_count = len(paired_profiled)

    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in associated:
        key = (
            row["Relationship Status"],
            str(row.get("Parent Network Fingerprint ID") or ""),
            str(row.get("Range Fingerprint ID") or ""),
            str(row.get("Association Family") or ""),
        )
        grouped[key].append(row)

    summary: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        status, network_fp, range_fp, association = key
        count = len(rows)
        paired_share = (
            round(count * 100.0 / paired_count, 1)
            if status == "PROFILE_PAIR" and paired_count else None
        )
        summary.append({
            "Relationship Status": status,
            "Network Fingerprint ID": network_fp,
            "Range Fingerprint ID": range_fp,
            "Association Family": association,
            "Range Count": count,
            "Share of Associated Ranges %": (
                round(count * 100.0 / associated_count, 1) if associated_count else None
            ),
            "Share of Paired Profiled Ranges %": paired_share,
            "Network View Distribution": _distribution([
                str(row.get("Network View") or "") for row in rows
            ]),
            "Notes": (
                "Both parent Network and Range have resolved deterministic fingerprints."
                if status == "PROFILE_PAIR" else
                "Range is profiled, but its parent Network core profile is unresolved."
                if status == "PARENT_PROFILE_UNRESOLVED" else
                ""
            ),
        })

    return summary, detail

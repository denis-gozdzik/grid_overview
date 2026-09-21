"""Decision-support analytics for Infoblox current-state standardization.

This module deliberately sits above WAPI normalization.  It never decides what
an approved standard should be; it summarizes observed configuration and
optionally overlays explicit human decisions loaded from YAML.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable

import yaml

from .models import CollectionResult


@dataclass(frozen=True)
class ParameterSpec:
    key: str
    base_key: str
    category: str
    label: str
    scope: str
    object_type: str
    source: str  # option | scalar
    option_number: int | None = None
    parameter: str | None = None
    evidence_sheet: str = "DHCP_Effective"


_SCOPE_OBJECT_TYPES = {
    "Grid": "grid:dhcpproperties",
    "Member": "member:dhcpproperties",
    "Network": "network",
    "Range": "range",
}


def _scoped_specs(
    base_key: str, category: str, label: str, scopes: tuple[str, ...], source: str,
    option_number: int | None = None, parameter: str | None = None,
    evidence_sheet: str = "DHCP_Effective",
) -> tuple[ParameterSpec, ...]:
    return tuple(
        ParameterSpec(
            key=f"{base_key}.{scope.lower()}", base_key=base_key, category=category,
            label=label, scope=scope, object_type=_SCOPE_OBJECT_TYPES[scope], source=source,
            option_number=option_number, parameter=parameter, evidence_sheet=evidence_sheet,
        )
        for scope in scopes
    )


PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    *_scoped_specs("dhcp.lease_time", "DHCP", "Default lease time", ("Grid", "Network", "Range"),
                   "option", 51, evidence_sheet="DHCP_Options"),
    *_scoped_specs("dhcp.dns_servers", "DHCP", "DNS servers", ("Grid", "Network", "Range"),
                   "option", 6, evidence_sheet="DHCP_Options"),
    *_scoped_specs("dhcp.domain_name", "DHCP", "Domain name", ("Grid", "Network", "Range"),
                   "option", 15, evidence_sheet="DHCP_Options"),
    *_scoped_specs("dhcp.domain_search", "DHCP", "Domain search", ("Grid", "Network", "Range"),
                   "option", 119, evidence_sheet="DHCP_Options"),
    *_scoped_specs("dhcp.router", "DHCP", "Router / gateway", ("Grid", "Network", "Range"),
                   "option", 3, evidence_sheet="DHCP_Options"),
    *_scoped_specs("dhcp.ntp_servers", "DHCP", "NTP servers", ("Grid", "Network", "Range"),
                   "option", 42, evidence_sheet="DHCP_Options"),
    *_scoped_specs("pxe.tftp_server_name", "PXE", "TFTP server name", ("Grid", "Network", "Range"),
                   "option", 66, evidence_sheet="DHCP_Options"),
    *_scoped_specs("pxe.bootfile_name_option", "PXE", "Bootfile name (option 67)", ("Grid", "Network", "Range"),
                   "option", 67, evidence_sheet="DHCP_Options"),
    *_scoped_specs("pxe.nextserver", "PXE", "Next server", ("Grid", "Member", "Network", "Range"),
                   "scalar", parameter="nextserver"),
    *_scoped_specs("pxe.bootserver", "PXE", "Boot server", ("Network", "Range"),
                   "scalar", parameter="bootserver"),
    *_scoped_specs("pxe.bootfile", "PXE", "Bootfile", ("Network", "Range"),
                   "scalar", parameter="bootfile"),
    *_scoped_specs("pxe.lease_time", "PXE", "PXE lease time", ("Grid", "Network", "Range"),
                   "scalar", parameter="pxe_lease_time"),
    *_scoped_specs("pxe.lease_enabled", "PXE", "PXE lease enabled", ("Grid", "Network", "Range"),
                   "scalar", parameter="enable_pxe_lease_time"),
    *_scoped_specs("dhcp.deny_bootp", "DHCP", "BOOTP denied", ("Grid", "Member", "Network", "Range"),
                   "scalar", parameter="deny_bootp"),
    *_scoped_specs("ddns.enabled", "DDNS", "DDNS enabled", ("Grid", "Member", "Network", "Range"),
                   "scalar", parameter="enable_ddns"),
    *_scoped_specs("ddns.domain", "DDNS", "DDNS domain", ("Network", "Range"),
                   "scalar", parameter="ddns_domainname"),
    *_scoped_specs("ddns.generate_hostname", "DDNS", "Generate hostname", ("Grid", "Member", "Network", "Range"),
                   "scalar", parameter="ddns_generate_hostname"),
    *_scoped_specs("ddns.ttl", "DDNS", "DDNS TTL", ("Grid", "Member", "Network"),
                   "scalar", parameter="ddns_ttl"),
    *_scoped_specs("ddns.update_fixed_addresses", "DDNS", "Update fixed addresses", ("Grid", "Member", "Network"),
                   "scalar", parameter="ddns_update_fixed_addresses"),
    *_scoped_specs("ddns.use_option81", "DDNS", "Use DHCP option 81", ("Grid", "Member", "Network"),
                   "scalar", parameter="ddns_use_option81"),
    *_scoped_specs("ddns.update_on_renewal", "DDNS", "DNS update on lease renewal",
                   ("Grid", "Member", "Network", "Range"), "scalar",
                   parameter="update_dns_on_lease_renewal"),
)

STANDARDIZATION_HEADERS = [
    "Parameter ID", "Category", "Parameter", "Scope", "Object Type", "Coverage", "Evidence Status",
    "Population Objects", "Query Evidence Objects", "Query Coverage %", "Confirmed Objects",
    "Objects Without Confirmed Value", "Grids in Scope", "Grids Assessed", "Distinct Observed Values",
    "Observed Values", "Common Observed Value", "Common Value Count", "Common Value %",
    "Local Override Count", "Override Eligible Objects", "Local Override %", "Inherited Count", "Inherited %",
    "Source Levels", "Source Distribution", "Consistency Classification", "Standardization Candidate",
    "Decision Status", "Proposed / Discussed Target", "Approved Target", "Exceptions Allowed", "Exception Rule",
    "Decision Owner", "Decision Date", "Decision Notes", "Evidence Sheet",
]

DECISION_HEADERS = [
    "Decision ID", "Category", "Parameter", "Scope", "Object Type", "Population Objects",
    "Query Coverage %", "Confirmed Objects", "Current Observed State", "Common Observed Value",
    "Coverage", "Proposed / Discussed Target", "Approved Target", "Status", "Exceptions Allowed",
    "Exception Rule", "Owner", "Decision Date", "Notes", "Persistence",
]

EXCEPTION_HEADERS = [
    "Grid", "Network View", "Object Type", "Object", "Parent Network", "Parameter ID", "Parameter",
    "Observed Effective Value", "Source Level", "Source Object", "Configured Here", "Approved Target",
    "Assessment State", "Exception Allowed", "Exception Rule", "Owner", "Potential Change Level",
    "Object Ref", "Source Ref", "Evidence Sheet",
]

DIFFERENCE_HEADERS = [
    "Category", "Parameter ID", "Parameter", "Scope", "Object Type", "Population Objects",
    "Query Coverage %", "Observed Values", "Distinct Values", "Confirmed Objects", "Grids",
    "Common Observed Value", "Common Value Count", "Common Value %", "Local Overrides", "Local Override %",
    "Source Levels", "Source Distribution", "Classification", "Coverage", "Notes",
]

_ALLOWED_DECISION_STATUSES = {"PENDING", "UNDER_REVIEW", "APPROVED", "REJECTED", "DEFERRED", "NOT_APPLICABLE"}
_AUTHORITATIVE_QUERY_STATES = {"COMPLETE", "EMPTY"}
_INCOMPLETE_QUERY_STATES = {"PARTIAL", "ERROR", "NOT_EXPOSED_BY_WAPI", "MANUAL_REVIEW_REQUIRED"}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def _percent(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100.0 / denominator, 1) if denominator else None


def _object_key(row: dict[str, Any]) -> tuple[str, str, str]:
    identity = row.get("object_ref") or row.get("object_name") or _json([
        row.get("network_view"), row.get("parent_network"), row.get("source_ref")
    ])
    return str(row.get("grid", "")), str(row.get("object_type", "")), str(identity)


def _spec_rows(spec: ParameterSpec, scalars: list[dict[str, Any]], options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if spec.source == "option":
        return [row for row in options
                if row.get("object_type") == spec.object_type
                and str(row.get("vendor_class", "DHCP")) == "DHCP"
                and str(row.get("option_number", "")) == str(spec.option_number)]
    return [row for row in scalars
            if row.get("object_type") == spec.object_type and row.get("parameter") == spec.parameter]


def _proven(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return at most one unambiguous confirmed value per object."""
    candidates = [row for row in rows if row.get("status") == "COMPLETE"
                  and row.get("multisource") is not True and row.get("effective_value") is not None]
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        grouped[_object_key(row)].append(row)
    proven: list[dict[str, Any]] = []
    for object_rows in grouped.values():
        signatures = {_json([
            row.get("effective_value"), row.get("source_level"), row.get("source_ref"),
            row.get("configured_here"), row.get("inherited"),
        ]) for row in object_rows}
        if len(signatures) == 1:
            proven.append(object_rows[0])
    return sorted(proven, key=lambda row: _object_key(row))


def _coverage_query_rows(coverage: list[dict[str, Any]], grid: str, object_type: str, query: str) -> list[dict[str, Any]]:
    return [row for row in coverage
            if str(row.get("Grid", "")) == grid
            and row.get("Object") == object_type
            and row.get("Query") == query
            and not row.get("Field")]


def _query_status(coverage: list[dict[str, Any]], grid: str, object_type: str, query: str) -> str:
    rows = _coverage_query_rows(coverage, grid, object_type, query)
    statuses = {str(row.get("Collection Status", "")) for row in rows if row.get("Collection Status")}
    if not statuses:
        return "UNKNOWN"
    for status in ("ERROR", "PARTIAL", "NOT_EXPOSED_BY_WAPI", "MANUAL_REVIEW_REQUIRED", "COMPLETE", "EMPTY"):
        if status in statuses:
            return status
    return sorted(statuses)[0]


def _scope_metrics(spec: ParameterSpec, results: list[CollectionResult], coverage: list[dict[str, Any]],
                   rows: list[dict[str, Any]]) -> dict[str, Any]:
    query = "raw" if spec.object_type == "grid:dhcpproperties" else "effective"
    row_keys_by_grid: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for row in rows:
        row_keys_by_grid[str(row.get("grid", ""))].add(_object_key(row))

    population_by_grid: dict[str, int] = {}
    query_by_grid: dict[str, int] = {}
    raw_status_by_grid: dict[str, str] = {}
    query_status_by_grid: dict[str, str] = {}
    for result in results:
        raw_count = len(result.records.get(spec.object_type, []))
        query_count = (raw_count if query == "raw"
                       else len(result.effective_records.get(spec.object_type, [])))
        observed_count = len(row_keys_by_grid.get(result.grid, set()))
        population_by_grid[result.grid] = max(raw_count, query_count, observed_count)
        query_by_grid[result.grid] = query_count
        raw_status_by_grid[result.grid] = _query_status(coverage, result.grid, spec.object_type, "raw")
        query_status_by_grid[result.grid] = _query_status(coverage, result.grid, spec.object_type, query)

    population = sum(population_by_grid.values())
    query_objects = sum(min(query_by_grid[grid], population_by_grid[grid])
                        for grid in population_by_grid)
    query_coverage = _percent(query_objects, population)
    grids_in_scope = sum(population_by_grid[grid] > 0 or raw_status_by_grid[grid] == "EMPTY"
                         for grid in population_by_grid)
    grids_assessed = sum(query_status_by_grid[grid] in _AUTHORITATIVE_QUERY_STATES
                         or query_by_grid[grid] > 0 for grid in population_by_grid)

    authoritative = bool(results) and all(
        raw_status_by_grid[grid] in _AUTHORITATIVE_QUERY_STATES
        and query_status_by_grid[grid] in _AUTHORITATIVE_QUERY_STATES
        and query_by_grid[grid] >= population_by_grid[grid]
        for grid in population_by_grid
    )
    any_incomplete = any(
        raw_status_by_grid[grid] in _INCOMPLETE_QUERY_STATES
        or query_status_by_grid[grid] in _INCOMPLETE_QUERY_STATES
        or raw_status_by_grid[grid] == "UNKNOWN" or query_status_by_grid[grid] == "UNKNOWN"
        for grid in population_by_grid
    )
    if authoritative:
        coverage_label = "HIGH"
        evidence_status = "EMPTY" if population == 0 else "COMPLETE"
    elif query_objects > 0:
        coverage_label = "MEDIUM"
        evidence_status = "PARTIAL"
    else:
        coverage_label = "LOW"
        if any(status == "ERROR" for status in query_status_by_grid.values()):
            evidence_status = "ERROR"
        elif any(status == "NOT_EXPOSED_BY_WAPI" for status in query_status_by_grid.values()):
            evidence_status = "NOT_EXPOSED_BY_WAPI"
        else:
            evidence_status = "INSUFFICIENT_DATA"
    if not any_incomplete and population == 0 and results:
        coverage_label, evidence_status = "HIGH", "EMPTY"

    return {
        "population": population,
        "query_objects": query_objects,
        "query_coverage": query_coverage,
        "coverage": coverage_label,
        "evidence_status": evidence_status,
        "grids_in_scope": grids_in_scope,
        "grids_assessed": grids_assessed,
        "population_by_grid": population_by_grid,
        "query_by_grid": query_by_grid,
        "query_status_by_grid": query_status_by_grid,
        "raw_status_by_grid": raw_status_by_grid,
    }


def _normalize_decision(key: str, value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError(f"Decision {key!r} must be a mapping")
    status = str(value.get("status", "PENDING") or "PENDING").upper()
    if status not in _ALLOWED_DECISION_STATUSES:
        raise ValueError(f"Decision {key!r} has unsupported status {status!r}")
    approved_exceptions = value.get("approved_exceptions", []) or []
    if not isinstance(approved_exceptions, list) or any(not isinstance(item, dict) for item in approved_exceptions):
        raise ValueError(f"Decision {key!r} approved_exceptions must be a list of mappings")
    return {
        "status": status,
        "proposed_target": value.get("proposed_target"),
        "approved_target": value.get("approved_target"),
        "exceptions_allowed": bool(value.get("exceptions_allowed", False)),
        "exception_rule": str(value.get("exception_rule", "") or ""),
        "owner": str(value.get("owner", "") or ""),
        "decision_date": str(value.get("decision_date", "") or ""),
        "notes": str(value.get("notes", "") or ""),
        "comparison_mode": str(value.get("comparison_mode", "exact") or "exact"),
        "approved_exceptions": approved_exceptions,
    }


def load_decisions(path: str | Path | None) -> dict[str, dict[str, Any]]:
    """Load explicit human decisions. Missing path means no decisions, never implicit approval."""
    if path is None:
        return {}
    source = Path(path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot load standardization decisions from {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Decision file root must be a mapping")
    decisions = payload.get("decisions", payload)
    if not isinstance(decisions, dict):
        raise ValueError("Decision file 'decisions' must be a mapping")
    known = {spec.key for spec in PARAMETER_SPECS}
    legacy = {spec.base_key for spec in PARAMETER_SPECS}
    legacy_used = sorted(set(decisions) & legacy)
    if legacy_used:
        suggestions = []
        for key in legacy_used:
            scoped = ", ".join(spec.key for spec in PARAMETER_SPECS if spec.base_key == key)
            suggestions.append(f"{key} -> {scoped}")
        raise ValueError("Unscoped decision IDs are no longer valid; choose a scope-specific ID: " + "; ".join(suggestions))
    unknown = sorted(set(decisions) - known)
    if unknown:
        raise ValueError("Unknown standardization decision IDs: " + ", ".join(unknown))
    return {str(key): _normalize_decision(str(key), value) for key, value in decisions.items()}


def _decision_for(spec: ParameterSpec, decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return decisions.get(spec.key, _normalize_decision(spec.key, {}))


def _distribution(proven: list[dict[str, Any]]) -> tuple[Counter[str], dict[str, Any]]:
    decoded: dict[str, Any] = {}
    counts: Counter[str] = Counter()
    for row in proven:
        key = _json(row.get("effective_value"))
        counts[key] += 1
        decoded[key] = row.get("effective_value")
    return counts, decoded


def _observed_values(counts: Counter[str], decoded: dict[str, Any], denominator: int | None = None,
                     limit: int = 8) -> str:
    ordered = sorted(counts.items(), key=lambda item: (-item[1], _display(decoded[item[0]])))
    parts = []
    for key, count in ordered[:limit]:
        if denominator:
            parts.append(f"{_display(decoded[key])} ({count}/{denominator}, {_percent(count, denominator):.1f}%)")
        else:
            parts.append(f"{_display(decoded[key])} ({count})")
    if len(ordered) > limit:
        parts.append(f"+{len(ordered) - limit} more")
    return "; ".join(parts)


def _source_distribution(proven: list[dict[str, Any]]) -> tuple[list[str], str]:
    counts = Counter(str(row.get("source_level")) for row in proven if row.get("source_level"))
    levels = sorted(counts)
    display = "; ".join(f"{level} ({counts[level]})" for level in sorted(counts, key=lambda key: (-counts[key], key)))
    return levels, display


def build_standardization(
    results: list[CollectionResult], coverage: list[dict[str, Any]],
    scalars: list[dict[str, Any]], options: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate normalized evidence into one row per parameter and object scope."""
    decisions = decisions or {}
    output: list[dict[str, Any]] = []
    for spec in PARAMETER_SPECS:
        rows = _spec_rows(spec, scalars, options)
        proven = _proven(rows)
        metrics = _scope_metrics(spec, results, coverage, rows)
        population = metrics["population"]
        counts, decoded = _distribution(proven)
        ordered = counts.most_common()
        highest = ordered[0][1] if ordered else 0
        tied = [key for key, count in ordered if count == highest]
        common_key = tied[0] if len(tied) == 1 else None
        common = decoded.get(common_key) if common_key is not None else None
        explicit_not_configured = bool(rows) and all(row.get("status") == "NOT_CONFIGURED" for row in rows)
        evidence_status = metrics["evidence_status"]
        if explicit_not_configured and metrics["coverage"] == "HIGH":
            evidence_status = "NOT_CONFIGURED"

        eligible_denominator = 0 if spec.object_type == "grid:dhcpproperties" else population
        local = [row for row in proven if row.get("configured_here") is True
                 and spec.object_type != "grid:dhcpproperties"]
        inherited = [row for row in proven if row.get("inherited") is True]
        source_levels, source_distribution = _source_distribution(proven)
        proven_grids = {str(row.get("grid", "")) for row in proven if row.get("grid")}
        scope_grids = {grid for grid, count in metrics["population_by_grid"].items() if count > 0}

        if metrics["coverage"] == "HIGH" and population == 0:
            classification = "NO_OBJECTS_IN_SCOPE"
        elif evidence_status == "NOT_CONFIGURED":
            classification = "NOT_CONFIGURED"
        elif not proven:
            evidence_status = "INSUFFICIENT_DATA"
            classification = "INSUFFICIENT_DATA"
        elif metrics["coverage"] == "HIGH" and len(scope_grids) > 1 and proven_grids != scope_grids:
            classification = "ONLY_IN_SOME_GRIDS"
        elif len(counts) > 1:
            classification = "MULTIPLE_VALUES"
        elif len(source_levels) > 1:
            classification = "DIFFERENT_SOURCE"
        elif local:
            classification = "LOCAL_OVERRIDES"
        else:
            classification = "CONSISTENT"

        if classification == "NO_OBJECTS_IN_SCOPE":
            candidate = "NOT_APPLICABLE"
        elif metrics["coverage"] == "LOW" or classification == "INSUFFICIENT_DATA":
            candidate = "BLOCKED_BY_DATA"
        elif metrics["coverage"] == "MEDIUM" or classification == "NOT_CONFIGURED":
            candidate = "NEEDS_ANALYSIS"
        else:
            candidate = "READY_FOR_REVIEW"

        decision = _decision_for(spec, decisions)
        output.append({
            "Parameter ID": spec.key,
            "Category": spec.category,
            "Parameter": spec.label,
            "Scope": spec.scope,
            "Object Type": spec.object_type,
            "Coverage": metrics["coverage"],
            "Evidence Status": evidence_status,
            "Population Objects": population,
            "Query Evidence Objects": metrics["query_objects"],
            "Query Coverage %": metrics["query_coverage"],
            "Confirmed Objects": len(proven),
            "Objects Without Confirmed Value": max(population - len(proven), 0),
            "Grids in Scope": metrics["grids_in_scope"],
            "Grids Assessed": metrics["grids_assessed"],
            "Distinct Observed Values": len(counts),
            "Observed Values": _observed_values(counts, decoded, population) if counts else "",
            "Common Observed Value": _display(common) if common_key is not None else "",
            "Common Value Count": highest if common_key is not None else None,
            "Common Value %": _percent(highest, population) if common_key is not None else None,
            "Local Override Count": len(local),
            "Override Eligible Objects": eligible_denominator,
            "Local Override %": _percent(len(local), eligible_denominator),
            "Inherited Count": len(inherited),
            "Inherited %": _percent(len(inherited), population),
            "Source Levels": ", ".join(source_levels),
            "Source Distribution": source_distribution,
            "Consistency Classification": classification,
            "Standardization Candidate": candidate,
            "Decision Status": decision["status"],
            "Proposed / Discussed Target": _display(decision["proposed_target"]),
            "Approved Target": _display(decision["approved_target"]),
            "Exceptions Allowed": decision["exceptions_allowed"],
            "Exception Rule": decision["exception_rule"],
            "Decision Owner": decision["owner"],
            "Decision Date": decision["decision_date"],
            "Decision Notes": decision["notes"],
            "Evidence Sheet": spec.evidence_sheet,
            "_common_key": common_key,
            "_rows": rows,
            "_proven": proven,
            "_decision": decision,
            "_population_by_grid": metrics["population_by_grid"],
        })
    return output


def decision_rows(standardization: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in standardization:
        state = item["Observed Values"] or item["Evidence Status"]
        rows.append({
            "Decision ID": item["Parameter ID"], "Category": item["Category"], "Parameter": item["Parameter"],
            "Scope": item["Scope"], "Object Type": item["Object Type"],
            "Population Objects": item["Population Objects"], "Query Coverage %": item["Query Coverage %"],
            "Confirmed Objects": item["Confirmed Objects"], "Current Observed State": state,
            "Common Observed Value": item["Common Observed Value"], "Coverage": item["Coverage"],
            "Proposed / Discussed Target": item["Proposed / Discussed Target"],
            "Approved Target": item["Approved Target"], "Status": item["Decision Status"],
            "Exceptions Allowed": item["Exceptions Allowed"], "Exception Rule": item["Exception Rule"],
            "Owner": item["Decision Owner"], "Decision Date": item["Decision Date"], "Notes": item["Decision Notes"],
            "Persistence": "Persist decisions in YAML via --decisions; generated XLSX edits are not imported automatically.",
        })
    return rows


def _coerce_target(target: Any, observed: Any) -> Any:
    if isinstance(observed, bool) and isinstance(target, str):
        lowered = target.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    if isinstance(observed, int) and not isinstance(observed, bool) and isinstance(target, str):
        try:
            return int(target.strip())
        except ValueError:
            return target
    if isinstance(observed, float) and isinstance(target, str):
        try:
            return float(target.strip())
        except ValueError:
            return target
    return target


def _matches_target(value: Any, target: Any, mode: str) -> bool:
    target = _coerce_target(target, value)
    if mode == "unordered_list":
        def values(candidate: Any) -> list[str] | None:
            if isinstance(candidate, list):
                return sorted(_display(item).strip() for item in candidate)
            if isinstance(candidate, str):
                return sorted(part.strip() for part in candidate.split(",") if part.strip())
            return None
        left, right = values(value), values(target)
        return left is not None and right is not None and left == right
    if not isinstance(value, (dict, list)) and not isinstance(target, (dict, list)):
        return _display(value).strip() == _display(target).strip()
    return _json(value) == _json(target)


def _approved_exception(row: dict[str, Any], decision: dict[str, Any]) -> bool:
    for selector in decision.get("approved_exceptions", []):
        field_map = {
            "grid": "grid", "object_ref": "object_ref", "object": "object_name",
            "object_name": "object_name", "network_view": "network_view", "parent_network": "parent_network",
        }
        if selector and all(str(row.get(field_map.get(key, key), "")) == str(value)
                            for key, value in selector.items() if key != "notes"):
            return True
    return False


def exception_rows(standardization: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return actionable object rows without duplicating ambiguous normalized evidence."""
    output: list[dict[str, Any]] = []
    for item in standardization:
        decision = item["_decision"]
        approved = decision["status"] == "APPROVED" and decision.get("approved_target") is not None
        common_key = item.get("_common_key")
        proven_by_key = {_object_key(row): row for row in item["_proven"]}
        all_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in item["_rows"]:
            all_by_key.setdefault(_object_key(row), row)
        candidate_rows = (all_by_key.items() if approved
                          else ((key, row) for key, row in proven_by_key.items()))
        for row_key, fallback_row in candidate_rows:
            row = proven_by_key.get(row_key, fallback_row)
            proven = row_key in proven_by_key
            state = None
            if approved:
                if not proven:
                    state = "INSUFFICIENT_DATA"
                elif _matches_target(row.get("effective_value"), decision["approved_target"], decision.get("comparison_mode", "exact")):
                    continue
                elif decision["exceptions_allowed"] and _approved_exception(row, decision):
                    state = "APPROVED_EXCEPTION"
                else:
                    state = "DEVIATION"
            elif proven:
                value_key = _json(row.get("effective_value"))
                is_local = row.get("configured_here") is True and row.get("object_type") != "grid:dhcpproperties"
                differs_from_common = common_key is not None and value_key != common_key
                if is_local or differs_from_common:
                    state = "PENDING_DECISION"
            if state is None:
                continue
            output.append({
                "Grid": row.get("grid"), "Network View": row.get("network_view"), "Object Type": row.get("object_type"),
                "Object": row.get("object_name"), "Parent Network": row.get("parent_network"),
                "Parameter ID": item["Parameter ID"], "Parameter": item["Parameter"],
                "Observed Effective Value": _display(row.get("effective_value")), "Source Level": row.get("source_level"),
                "Source Object": row.get("source_object"), "Configured Here": row.get("configured_here"),
                "Approved Target": _display(decision.get("approved_target")), "Assessment State": state,
                "Exception Allowed": decision["exceptions_allowed"], "Exception Rule": decision["exception_rule"],
                "Owner": decision["owner"], "Potential Change Level": row.get("source_level") or "UNKNOWN",
                "Object Ref": row.get("object_ref"), "Source Ref": row.get("source_ref"),
                "Evidence Sheet": item["Evidence Sheet"],
            })
    return sorted(output, key=lambda row: tuple(str(row.get(key, "")) for key in
                  ("Assessment State", "Parameter ID", "Grid", "Network View", "Object Type", "Object")))


def grid_comparison_rows(standardization: list[dict[str, Any]], grids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    headers = ["Category", "Parameter ID", "Parameter", "Scope", "Object Type", *grids,
               "Distinct Values", "Common Observed Value", "Consistency", "Local Overrides", "Coverage", "Notes"]
    if len(grids) < 2:
        return [{"Category": "Comparison", "Parameter ID": "", "Parameter": "Cross-Grid comparison",
                 "Scope": "", "Object Type": "", **{grid: "" for grid in grids}, "Distinct Values": "",
                 "Common Observed Value": "", "Consistency": "NOT_APPLICABLE", "Local Overrides": "",
                 "Coverage": "", "Notes": "Cross-Grid comparison requires at least two Grids."}], headers
    output = []
    for item in standardization:
        by_grid: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in item["_proven"]:
            by_grid[str(row.get("grid", ""))].append(row)
        values = Counter()
        display_by_grid = {}
        for grid in grids:
            counts, decoded = _distribution(by_grid.get(grid, []))
            denominator = int(item.get("_population_by_grid", {}).get(grid, 0) or 0)
            display_by_grid[grid] = (_observed_values(counts, decoded, denominator)
                                     if counts else "NO_CONFIRMED_EVIDENCE")
            values.update(counts)
        output.append({
            "Category": item["Category"], "Parameter ID": item["Parameter ID"], "Parameter": item["Parameter"],
            "Scope": item["Scope"], "Object Type": item["Object Type"], **display_by_grid,
            "Distinct Values": len(values), "Common Observed Value": item["Common Observed Value"],
            "Consistency": item["Consistency Classification"], "Local Overrides": item["Local Override Count"],
            "Coverage": item["Coverage"],
            "Notes": "Observed effective values within this scope only; common value is not an approved standard.",
        })
    return output, headers


def difference_rows(standardization: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for item in standardization:
        if item["Consistency Classification"] == "CONSISTENT" and not item["Local Override Count"]:
            continue
        output.append({
            "Category": item["Category"], "Parameter ID": item["Parameter ID"], "Parameter": item["Parameter"],
            "Scope": item["Scope"], "Object Type": item["Object Type"],
            "Population Objects": item["Population Objects"], "Query Coverage %": item["Query Coverage %"],
            "Observed Values": item["Observed Values"], "Distinct Values": item["Distinct Observed Values"],
            "Confirmed Objects": item["Confirmed Objects"], "Grids": item["Grids Assessed"],
            "Common Observed Value": item["Common Observed Value"], "Common Value Count": item["Common Value Count"],
            "Common Value %": item["Common Value %"], "Local Overrides": item["Local Override Count"],
            "Local Override %": item["Local Override %"], "Source Levels": item["Source Levels"],
            "Source Distribution": item["Source Distribution"], "Classification": item["Consistency Classification"],
            "Coverage": item["Coverage"],
            "Notes": "Observed difference only; no deviation exists until an approved target is defined.",
        })
    return output


def workbook_standardization_rows(standardization: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip internal evidence objects before Excel serialization."""
    return [{key: row.get(key) for key in STANDARDIZATION_HEADERS} for row in standardization]


def decision_template_payload(standardization: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = {}
    for row in standardization:
        decision = row["_decision"]
        decisions[row["Parameter ID"]] = {
            "status": decision["status"],
            "proposed_target": decision["proposed_target"],
            "approved_target": decision["approved_target"],
            "exceptions_allowed": decision["exceptions_allowed"],
            "exception_rule": decision["exception_rule"],
            "owner": decision["owner"],
            "decision_date": decision["decision_date"],
            "notes": decision["notes"],
            "comparison_mode": decision["comparison_mode"],
            "approved_exceptions": decision["approved_exceptions"],
        }
    return {"version": 2, "decisions": decisions}


def write_decision_template(standardization: list[dict[str, Any]], path: str | Path) -> None:
    Path(path).write_text(yaml.safe_dump(decision_template_payload(standardization), sort_keys=False,
                                         allow_unicode=True), encoding="utf-8")

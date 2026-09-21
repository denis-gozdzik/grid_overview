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
    category: str
    label: str
    scope: str
    source: str  # option | scalar
    option_number: int | None = None
    parameter: str | None = None
    evidence_sheet: str = "DHCP_Effective"


PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec("dhcp.lease_time", "DHCP", "Default lease time", "Grid / Network / Range", "option", 51, evidence_sheet="DHCP_Options"),
    ParameterSpec("dhcp.dns_servers", "DHCP", "DNS servers", "Grid / Network / Range", "option", 6, evidence_sheet="DHCP_Options"),
    ParameterSpec("dhcp.domain_name", "DHCP", "Domain name", "Grid / Network / Range", "option", 15, evidence_sheet="DHCP_Options"),
    ParameterSpec("dhcp.domain_search", "DHCP", "Domain search", "Grid / Network / Range", "option", 119, evidence_sheet="DHCP_Options"),
    ParameterSpec("dhcp.router", "DHCP", "Router / gateway", "Grid / Network / Range", "option", 3, evidence_sheet="DHCP_Options"),
    ParameterSpec("dhcp.ntp_servers", "DHCP", "NTP servers", "Grid / Network / Range", "option", 42, evidence_sheet="DHCP_Options"),
    ParameterSpec("pxe.tftp_server_name", "PXE", "TFTP server name", "Grid / Network / Range", "option", 66, evidence_sheet="DHCP_Options"),
    ParameterSpec("pxe.bootfile_name_option", "PXE", "Bootfile name (option 67)", "Grid / Network / Range", "option", 67, evidence_sheet="DHCP_Options"),
    ParameterSpec("pxe.nextserver", "PXE", "Next server", "Grid / Member / Network / Range", "scalar", parameter="nextserver"),
    ParameterSpec("pxe.bootserver", "PXE", "Boot server", "Network / Range", "scalar", parameter="bootserver"),
    ParameterSpec("pxe.bootfile", "PXE", "Bootfile", "Network / Range", "scalar", parameter="bootfile"),
    ParameterSpec("pxe.lease_time", "PXE", "PXE lease time", "Grid / Network / Range", "scalar", parameter="pxe_lease_time"),
    ParameterSpec("pxe.lease_enabled", "PXE", "PXE lease enabled", "Grid / Network / Range", "scalar", parameter="enable_pxe_lease_time"),
    ParameterSpec("dhcp.deny_bootp", "DHCP", "BOOTP denied", "Grid / Member / Network / Range", "scalar", parameter="deny_bootp"),
    ParameterSpec("ddns.enabled", "DDNS", "DDNS enabled", "Grid / Member / Network / Range", "scalar", parameter="enable_ddns"),
    ParameterSpec("ddns.domain", "DDNS", "DDNS domain", "Network / Range", "scalar", parameter="ddns_domainname"),
    ParameterSpec("ddns.generate_hostname", "DDNS", "Generate hostname", "Grid / Member / Network / Range", "scalar", parameter="ddns_generate_hostname"),
    ParameterSpec("ddns.ttl", "DDNS", "DDNS TTL", "Grid / Member / Network", "scalar", parameter="ddns_ttl"),
    ParameterSpec("ddns.update_fixed_addresses", "DDNS", "Update fixed addresses", "Grid / Member / Network", "scalar", parameter="ddns_update_fixed_addresses"),
    ParameterSpec("ddns.use_option81", "DDNS", "Use DHCP option 81", "Grid / Member / Network", "scalar", parameter="ddns_use_option81"),
    ParameterSpec("ddns.update_on_renewal", "DDNS", "DNS update on lease renewal", "Grid / Member / Network / Range", "scalar", parameter="update_dns_on_lease_renewal"),
)

STANDARDIZATION_HEADERS = [
    "Parameter ID", "Category", "Parameter", "Scope", "Coverage", "Evidence Status",
    "Objects Assessed", "Confirmed Objects", "Grids Assessed", "Distinct Observed Values",
    "Observed Values", "Common Observed Value", "Common Value Count", "Common Value %",
    "Local Override Count", "Override Eligible Objects", "Local Override %", "Inherited Count",
    "Source Levels", "Consistency Classification", "Standardization Candidate", "Decision Status",
    "Proposed / Discussed Target", "Approved Target", "Exceptions Allowed", "Exception Rule",
    "Decision Owner", "Decision Date", "Decision Notes", "Evidence Sheet",
]

DECISION_HEADERS = [
    "Decision ID", "Category", "Parameter", "Current Observed State", "Common Observed Value",
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
    "Category", "Parameter ID", "Parameter", "Observed Values", "Distinct Values", "Confirmed Objects",
    "Grids", "Common Observed Value", "Common Value Count", "Common Value %", "Local Overrides",
    "Source Levels", "Classification", "Coverage", "Notes",
]

_ALLOWED_DECISION_STATUSES = {"PENDING", "UNDER_REVIEW", "APPROVED", "REJECTED", "DEFERRED", "NOT_APPLICABLE"}


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


def _spec_rows(spec: ParameterSpec, scalars: list[dict[str, Any]], options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if spec.source == "option":
        return [row for row in options
                if str(row.get("vendor_class", "DHCP")) == "DHCP"
                and str(row.get("option_number", "")) == str(spec.option_number)]
    return [row for row in scalars if row.get("parameter") == spec.parameter]


def _proven(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("status") == "COMPLETE"
            and row.get("multisource") is not True and row.get("effective_value") is not None]


def _coverage_state(rows: list[dict[str, Any]]) -> tuple[str, str]:
    if not rows:
        return "LOW", "INSUFFICIENT_DATA"
    complete = sum(row.get("status") == "COMPLETE" and row.get("multisource") is not True
                   and row.get("effective_value") is not None for row in rows)
    unresolved = sum(row.get("status") in {None, "PARTIAL", "ERROR"} or row.get("multisource") is True for row in rows)
    not_configured = sum(row.get("status") == "NOT_CONFIGURED" for row in rows)
    if complete and not unresolved:
        return "HIGH", "COMPLETE"
    if complete:
        return "MEDIUM", "PARTIAL"
    if not_configured == len(rows):
        return "HIGH", "NOT_CONFIGURED"
    return "LOW", "INSUFFICIENT_DATA"


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


def _observed_values(counts: Counter[str], decoded: dict[str, Any], limit: int = 8) -> str:
    ordered = sorted(counts.items(), key=lambda item: (-item[1], _display(decoded[item[0]])))
    parts = [f"{_display(decoded[key])} ({count})" for key, count in ordered[:limit]]
    if len(ordered) > limit:
        parts.append(f"+{len(ordered) - limit} more")
    return "; ".join(parts)


def build_standardization(
    results: list[CollectionResult], coverage: list[dict[str, Any]],
    scalars: list[dict[str, Any]], options: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate normalized evidence into one row per standardization question."""
    decisions = decisions or {}
    all_grids = {result.grid for result in results}
    output: list[dict[str, Any]] = []
    for spec in PARAMETER_SPECS:
        rows = _spec_rows(spec, scalars, options)
        proven = _proven(rows)
        counts, decoded = _distribution(proven)
        ordered = counts.most_common()
        highest = ordered[0][1] if ordered else 0
        tied = [key for key, count in ordered if count == highest]
        common_key = tied[0] if len(tied) == 1 else None
        common = decoded.get(common_key) if common_key is not None else None
        coverage_label, evidence_status = _coverage_state(rows)
        eligible = [row for row in proven if row.get("object_type") != "grid:dhcpproperties"]
        local = [row for row in eligible if row.get("configured_here") is True]
        inherited = [row for row in eligible if row.get("inherited") is True]
        source_levels = sorted({str(row.get("source_level", "")) for row in proven if row.get("source_level")})
        observed_grids = {str(row.get("grid", "")) for row in rows if row.get("grid")}
        if evidence_status == "NOT_CONFIGURED":
            classification = "NOT_CONFIGURED"
        elif not proven:
            classification = "INSUFFICIENT_DATA"
        elif len(all_grids) > 1 and observed_grids and observed_grids != all_grids:
            classification = "ONLY_IN_SOME_GRIDS"
        elif len(counts) > 1:
            classification = "MULTIPLE_VALUES"
        elif len(source_levels) > 1:
            classification = "DIFFERENT_SOURCE"
        elif local:
            classification = "LOCAL_OVERRIDES"
        else:
            classification = "CONSISTENT"
        if coverage_label == "LOW":
            candidate = "BLOCKED_BY_DATA"
        elif classification in {"NOT_CONFIGURED"}:
            candidate = "NEEDS_ANALYSIS"
        else:
            candidate = "READY_FOR_REVIEW"
        decision = _decision_for(spec, decisions)
        output.append({
            "Parameter ID": spec.key,
            "Category": spec.category,
            "Parameter": spec.label,
            "Scope": spec.scope,
            "Coverage": coverage_label,
            "Evidence Status": evidence_status,
            "Objects Assessed": len(rows),
            "Confirmed Objects": len(proven),
            "Grids Assessed": len(observed_grids),
            "Distinct Observed Values": len(counts),
            "Observed Values": _observed_values(counts, decoded) if counts else "",
            "Common Observed Value": _display(common) if common_key is not None else "",
            "Common Value Count": highest if common_key is not None else None,
            "Common Value %": _percent(highest, len(proven)) if common_key is not None else None,
            "Local Override Count": len(local),
            "Override Eligible Objects": len(eligible),
            "Local Override %": _percent(len(local), len(eligible)),
            "Inherited Count": len(inherited),
            "Source Levels": ", ".join(source_levels),
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
        })
    return output


def decision_rows(standardization: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in standardization:
        state = item["Observed Values"] or item["Evidence Status"]
        rows.append({
            "Decision ID": item["Parameter ID"], "Category": item["Category"], "Parameter": item["Parameter"],
            "Current Observed State": state, "Common Observed Value": item["Common Observed Value"],
            "Coverage": item["Coverage"], "Proposed / Discussed Target": item["Proposed / Discussed Target"],
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
    """Return actionable rows only; ordinary matches are summarized, not flooded into Excel."""
    output: list[dict[str, Any]] = []
    for item in standardization:
        decision = item["_decision"]
        approved = decision["status"] == "APPROVED" and decision.get("approved_target") is not None
        common_key = item.get("_common_key")
        for row in item["_rows"]:
            proven = row.get("status") == "COMPLETE" and row.get("multisource") is not True and row.get("effective_value") is not None
            state = None
            if approved:
                if not proven:
                    state = "INSUFFICIENT_DATA"
                elif _matches_target(row.get("effective_value"), decision["approved_target"], decision.get("comparison_mode", "exact")):
                    continue  # Matches are counted in Standardization; Exceptions stays actionable.
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
    headers = ["Category", "Parameter ID", "Parameter", *grids,
               "Distinct Values", "Common Observed Value", "Consistency", "Local Overrides", "Coverage", "Notes"]
    if len(grids) < 2:
        return [{"Category": "Comparison", "Parameter ID": "", "Parameter": "Cross-Grid comparison",
                 **{grid: "" for grid in grids}, "Distinct Values": "", "Common Observed Value": "",
                 "Consistency": "NOT_APPLICABLE", "Local Overrides": "", "Coverage": "",
                 "Notes": "Cross-Grid comparison requires at least two Grids."}], headers
    output = []
    for item in standardization:
        by_grid: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in item["_proven"]:
            by_grid[str(row.get("grid", ""))].append(row)
        values = Counter()
        display_by_grid = {}
        for grid in grids:
            counts, decoded = _distribution(by_grid.get(grid, []))
            display_by_grid[grid] = _observed_values(counts, decoded) if counts else "NO_CONFIRMED_EVIDENCE"
            values.update(counts)
        decoded_all = {_json(row.get("effective_value")): row.get("effective_value") for row in item["_proven"]}
        output.append({
            "Category": item["Category"], "Parameter ID": item["Parameter ID"], "Parameter": item["Parameter"],
            **display_by_grid, "Distinct Values": len(values), "Common Observed Value": item["Common Observed Value"],
            "Consistency": item["Consistency Classification"], "Local Overrides": item["Local Override Count"],
            "Coverage": item["Coverage"], "Notes": "Observed effective values only; common value is not an approved standard.",
        })
    return output, headers


def difference_rows(standardization: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for item in standardization:
        if item["Consistency Classification"] == "CONSISTENT" and not item["Local Override Count"]:
            continue
        output.append({
            "Category": item["Category"], "Parameter ID": item["Parameter ID"], "Parameter": item["Parameter"],
            "Observed Values": item["Observed Values"], "Distinct Values": item["Distinct Observed Values"],
            "Confirmed Objects": item["Confirmed Objects"], "Grids": item["Grids Assessed"],
            "Common Observed Value": item["Common Observed Value"], "Common Value Count": item["Common Value Count"],
            "Common Value %": item["Common Value %"], "Local Overrides": item["Local Override Count"],
            "Source Levels": item["Source Levels"], "Classification": item["Consistency Classification"],
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
    return {"version": 1, "decisions": decisions}


def write_decision_template(standardization: list[dict[str, Any]], path: str | Path) -> None:
    Path(path).write_text(yaml.safe_dump(decision_template_payload(standardization), sort_keys=False,
                                         allow_unicode=True), encoding="utf-8")

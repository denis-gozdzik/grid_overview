"""Evidence readiness for future profile discovery, using scoped analytics only.

This layer neither resolves WAPI values nor creates configuration fingerprints.
The existing Standardization rows remain the authority for evidence accounting.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Any, Iterable

from .standardization import PARAMETER_SPECS, ParameterSpec


@dataclass(frozen=True)
class ProfileInputSpec:
    profile: str
    input_key: str
    label: str
    source_parameter_id: str
    scope: str
    semantic_role: str = "DIRECT"


_DHCP_INPUTS = (
    ("dhcp.lease_time", "lease_time", "Default lease time", "DIRECT"),
    ("dhcp.dns_servers", "dns_servers", "DNS servers", "DIRECT"),
    ("dhcp.domain_name", "domain_name", "Domain name", "DIRECT"),
    ("dhcp.domain_search", "domain_search", "Domain search", "DIRECT"),
    ("dhcp.router", "gateway_convention", "Gateway convention (router evidence)", "DERIVED_LATER"),
    ("dhcp.ntp_servers", "ntp_servers", "NTP servers", "DIRECT"),
    ("dhcp.deny_bootp", "deny_bootp", "BOOTP denied", "DIRECT"),
)
_DDNS_NETWORK_INPUTS = (
    ("ddns.enabled", "ddns_enabled", "DDNS enabled", "DIRECT"),
    ("ddns.domain", "ddns_domain", "DDNS domain", "DIRECT"),
    ("ddns.generate_hostname", "ddns_generate_hostname", "Generate hostname", "DIRECT"),
    ("ddns.ttl", "ddns_ttl", "DDNS TTL", "DIRECT"),
    ("ddns.update_fixed_addresses", "ddns_update_fixed_addresses", "Update fixed addresses", "DIRECT"),
    ("ddns.use_option81", "ddns_use_option81", "Use DHCP option 81", "DIRECT"),
    ("ddns.update_on_renewal", "ddns_update_on_renewal", "DNS update on lease renewal", "DIRECT"),
)
# Deliberately explicit: removing a supported parameter must fail validation,
# rather than silently shrink the candidate set through dynamic filtering.
_DDNS_RANGE_INPUTS = (
    ("ddns.enabled", "ddns_enabled", "DDNS enabled", "DIRECT"),
    ("ddns.domain", "ddns_domain", "DDNS domain", "DIRECT"),
    ("ddns.generate_hostname", "ddns_generate_hostname", "Generate hostname", "DIRECT"),
    ("ddns.update_on_renewal", "ddns_update_on_renewal", "DNS update on lease renewal", "DIRECT"),
)
_PXE_INPUTS = (
    ("pxe.nextserver", "pxe_nextserver", "Next server", "DIRECT"),
    ("pxe.bootserver", "pxe_bootserver", "Boot server", "DIRECT"),
    ("pxe.bootfile", "pxe_bootfile", "Bootfile", "DIRECT"),
    ("pxe.tftp_server_name", "pxe_tftp_server_name", "TFTP server name", "DIRECT"),
    ("pxe.bootfile_name_option", "pxe_bootfile_name_option", "Bootfile name (option 67)", "DIRECT"),
    ("pxe.lease_time", "pxe_lease_time", "PXE lease time", "DIRECT"),
    ("pxe.lease_enabled", "pxe_lease_enabled", "PXE lease enabled", "DIRECT"),
)


def _inputs(scope: str, candidates: tuple[tuple[str, str, str, str], ...]) -> tuple[ProfileInputSpec, ...]:
    return tuple(ProfileInputSpec(f"{scope} Profile v1", key, label, f"{parameter}.{scope.lower()}", scope, role)
                 for parameter, key, label, role in candidates)


PROFILE_INPUT_SPECS = (
    *_inputs("Network", _DHCP_INPUTS + _DDNS_NETWORK_INPUTS + _PXE_INPUTS),
    *_inputs("Range", _DHCP_INPUTS + _DDNS_RANGE_INPUTS + _PXE_INPUTS),
)

_EVIDENCE_HEADERS = [
    "Required Field", "Required Field Status", "Population Objects", "Query Evidence Objects",
    "Query Coverage %", "Collection Status", "Confirmed Objects", "Confirmed Value %",
    "Explicit Not Configured", "Resolved Evidence %", "Unresolved Objects", "Unresolved %", "Evidence Status",
]
PROFILE_READINESS_HEADERS = [
    "Profile", "Input Key", "Input", "Semantic Role", "Parameter ID", "Scope",
    *_EVIDENCE_HEADERS, "Readiness", "Readiness Reason",
]
PROFILE_SUMMARY_HEADERS = [
    "Profile", "Candidate Inputs", "Applicable Inputs", "READY", "CONDITIONAL", "NOT_READY",
    "NOT_APPLICABLE", "Ready Input %",
]


def validate_profile_inputs(specs: Iterable[ProfileInputSpec] = PROFILE_INPUT_SPECS,
                            parameter_specs: Iterable[ParameterSpec] = PARAMETER_SPECS) -> None:
    """Fail at development time if profile inputs drift from supported parameters."""
    parameters = {parameter.key: parameter for parameter in parameter_specs}
    seen_keys: set[tuple[str, str]] = set()
    seen_parameters: set[tuple[str, str]] = set()
    for spec in specs:
        parameter = parameters.get(spec.source_parameter_id)
        if parameter is None:
            raise ValueError(f"Unknown profile input Parameter ID: {spec.source_parameter_id}")
        if (spec.scope not in {"Network", "Range"} or parameter.scope != spec.scope
                or parameter.object_type != spec.scope.lower()
                or spec.profile != f"{spec.scope} Profile v1"):
            raise ValueError(f"Profile input scope mismatch: {spec.source_parameter_id}")
        if not spec.input_key or not spec.label:
            raise ValueError("Profile input key and label must be nonempty")
        if spec.semantic_role not in {"DIRECT", "DERIVED_LATER", "COMPOSITE_LATER"}:
            raise ValueError(f"Unknown profile input semantic role: {spec.semantic_role}")
        key = (spec.profile, spec.input_key)
        parameter_key = (spec.profile, spec.source_parameter_id)
        if key in seen_keys or parameter_key in seen_parameters:
            raise ValueError(f"Duplicate profile input: {spec.profile} / {spec.input_key}")
        seen_keys.add(key)
        seen_parameters.add(parameter_key)


def _classify(row: dict[str, Any]) -> tuple[str, str]:
    population = row.get("Population Objects")
    if type(population) is not int or population < 0:
        return "NOT_READY", "Population evidence unavailable or invalid"
    collection = row.get("Collection Status")
    if population == 0:
        if collection in {"COMPLETE", "EMPTY"}:
            return "NOT_APPLICABLE", "No objects in scope"
        return "NOT_READY", (
            "Population could not be established; "
            f"query collection is {str(collection or 'UNKNOWN').lower()}"
        )
    if row.get("Required Field Status") == "NOT_EXPOSED_BY_WAPI":
        return "NOT_READY", "Required WAPI field not exposed"
    if collection != "COMPLETE":
        return "NOT_READY", f"Query collection is {str(collection or 'UNKNOWN').lower()}"
    evidence = row.get("Evidence Status")
    if evidence not in {"COMPLETE", "PARTIAL", "NOT_CONFIGURED"}:
        return "NOT_READY", f"Parameter evidence status is {evidence or 'UNKNOWN'}"
    field_status = row.get("Required Field Status")
    if field_status not in {"AVAILABLE", "AVAILABLE_OR_NOT_FLAGGED", "NOT_EXPOSED_IN_SOME_GRIDS"}:
        return "NOT_READY", f"Required field availability is {field_status or 'UNKNOWN'}"

    # Keep the rounded percentage for display, but make threshold decisions from
    # integer evidence counts so a value such as 94.96% cannot round to 95.0%
    # and be promoted to READY.
    displayed_resolved = row.get("Resolved Evidence %")
    if (isinstance(displayed_resolved, bool) or not isinstance(displayed_resolved, (int, float))
            or not 0 <= displayed_resolved <= 100 or not math.isfinite(displayed_resolved)):
        return "NOT_READY", "Resolved evidence percentage unavailable or invalid"
    confirmed = row.get("Confirmed Objects")
    not_configured = row.get("Explicit Not Configured")
    if (type(confirmed) is not int or confirmed < 0
            or type(not_configured) is not int or not_configured < 0
            or confirmed + not_configured > population):
        return "NOT_READY", "Resolved evidence counts unavailable or invalid"
    resolved_count = confirmed + not_configured
    resolved_exact = resolved_count * 100.0 / population

    readiness = ("READY" if resolved_exact >= 95.0
                 else "CONDITIONAL" if resolved_exact >= 80.0
                 else "NOT_READY")
    reason = (
        f"{'Only ' if readiness == 'NOT_READY' else ''}"
        f"{resolved_count}/{population} resolved evidence ({resolved_exact:.2f}% exact)"
    )
    unresolved = row.get("Unresolved Objects")
    if isinstance(unresolved, int) and unresolved > 0:
        reason += f"; {unresolved}/{population} unresolved"
    if field_status == "NOT_EXPOSED_IN_SOME_GRIDS":
        reason += "; required field not exposed in some Grids"
    return readiness, reason


def build_profile_readiness(standardization: Iterable[dict[str, Any]],
                            specs: Iterable[ProfileInputSpec] = PROFILE_INPUT_SPECS) -> list[dict[str, Any]]:
    """Project existing scoped evidence into a deterministic candidate matrix.

    Missing source rows stay unknown; neither object counts nor NOT_CONFIGURED
    states are fabricated. Percentages retain Standardization's display precision.
    """
    candidates = tuple(specs)
    validate_profile_inputs(candidates)
    wanted = {spec.source_parameter_id for spec in candidates}
    indexed: dict[str, dict[str, Any]] = {}
    for row in standardization:
        parameter_id = row.get("Parameter ID")
        if parameter_id not in wanted:
            continue
        if parameter_id in indexed:
            raise ValueError(f"Duplicate Standardization Parameter ID: {parameter_id}")
        indexed[parameter_id] = row
    parameters = {parameter.key: parameter for parameter in PARAMETER_SPECS}
    output = []
    for spec in candidates:
        source = indexed.get(spec.source_parameter_id)
        parameter = parameters[spec.source_parameter_id]
        if source is not None and (
            source.get("Scope", spec.scope) != spec.scope
            or source.get("Object Type", parameter.object_type) != parameter.object_type
            or source.get("Required Field", parameter.required_field) != parameter.required_field
        ):
            raise ValueError(f"Standardization evidence scope/field mismatch: {spec.source_parameter_id}")
        row = {
            "Profile": spec.profile, "Input Key": spec.input_key, "Input": spec.label,
            "Semantic Role": spec.semantic_role, "Parameter ID": spec.source_parameter_id, "Scope": spec.scope,
            **{header: (source or {}).get(header) for header in _EVIDENCE_HEADERS},
        }
        if source is None:
            row.update({"Required Field": parameter.required_field, "Required Field Status": "UNKNOWN",
                        "Collection Status": "UNKNOWN", "Evidence Status": "INSUFFICIENT_DATA",
                        "Readiness": "NOT_READY", "Readiness Reason": "Standardization evidence unavailable"})
        else:
            row["Readiness"], row["Readiness Reason"] = _classify(row)
        output.append(row)
    return output


def profile_readiness_summary(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Count candidate inputs, never objects; exclude NOT_APPLICABLE from the rate."""
    counts: dict[str, Counter[str]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["Profile"], row["Input Key"])
        if key in seen:
            raise ValueError(f"Duplicate profile readiness input: {key[0]} / {key[1]}")
        seen.add(key)
        state = row["Readiness"]
        if state not in {"READY", "CONDITIONAL", "NOT_READY", "NOT_APPLICABLE"}:
            raise ValueError(f"Unknown profile readiness state: {state}")
        counts.setdefault(row["Profile"], Counter())[state] += 1
    output = []
    for profile in sorted(counts):
        states = counts[profile]
        total = sum(states.values())
        applicable = total - states["NOT_APPLICABLE"]
        output.append({
            "Profile": profile, "Candidate Inputs": total, "Applicable Inputs": applicable,
            **{state: states[state] for state in ("READY", "CONDITIONAL", "NOT_READY", "NOT_APPLICABLE")},
            "Ready Input %": round(states["READY"] * 100.0 / applicable, 1) if applicable else None,
        })
    return output


validate_profile_inputs()

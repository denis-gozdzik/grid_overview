"""Evidence readiness for future profile discovery, using scoped analytics only.

This layer neither resolves WAPI values nor creates configuration fingerprints.
The existing Standardization rows remain the authority for evidence accounting.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import math
from typing import Any, Iterable

from .models import CollectionResult
from .profile_population import (
    NETWORK_POPULATION_BASIS, RANGE_DHCP_ASSOCIATED_BASIS,
    RANGE_INFOBLOX_MANAGED_BASIS,
    dhcp_associated_range_keys, dhcp_relevant_networks, effective_network_keys,
    effective_range_keys, effective_records_by_key, infoblox_managed_range_keys,
    ms_server_range_keys, normalized_object_key,
)
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
    ("pxe.lease_enabled", "pxe_lease_enabled", "PXE lease enabled", "COMPOSITE_LATER"),
)


def _inputs(scope: str, candidates: tuple[tuple[str, str, str, str], ...]) -> tuple[ProfileInputSpec, ...]:
    return tuple(ProfileInputSpec(f"{scope} Profile v1", key, label, f"{parameter}.{scope.lower()}", scope, role)
                 for parameter, key, label, role in candidates)


PROFILE_INPUT_SPECS = (
    *_inputs("Network", _DHCP_INPUTS + _DDNS_NETWORK_INPUTS + _PXE_INPUTS),
    *_inputs("Range", _DHCP_INPUTS + _DDNS_RANGE_INPUTS + _PXE_INPUTS),
)

_EVIDENCE_HEADERS = [
    "Required Field", "Required Field Status", "Population Objects", "Excluded By Applicability",
    "Query Evidence Objects", "Query Coverage %", "Collection Status", "Confirmed Objects", "Confirmed Value %",
    "Explicit Not Configured", "Resolved Evidence %", "Unresolved Objects", "Unresolved %", "Evidence Status",
]
PROFILE_READINESS_HEADERS = [
    "Profile", "Input Key", "Input", "Semantic Role", "Parameter ID", "Scope",
    "Population Basis", "Source Population Objects",
    *_EVIDENCE_HEADERS, "Readiness", "Readiness Reason",
]
PROFILE_SUMMARY_HEADERS = [
    "Profile", "Candidate Inputs", "Applicable Inputs", "READY", "CONDITIONAL", "NOT_READY",
    "DEFERRED", "NOT_APPLICABLE", "Ready Input %",
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
        source_population = row.get("Source Population Objects")
        if (row.get("Population Basis") == NETWORK_POPULATION_BASIS
                and isinstance(source_population, int) and source_population > 0):
            return "NOT_READY", "No DHCP-relevant Network candidates identified from current evidence"
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


def _percent(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100.0 / denominator, 1) if denominator else None


def _profile_parameter_rows(spec: ProfileInputSpec, scalars: list[dict[str, Any]],
                            options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parameter = next(item for item in PARAMETER_SPECS if item.key == spec.source_parameter_id)
    if parameter.source == "option":
        return [row for row in options
                if row.get("object_type") == parameter.object_type
                and str(row.get("vendor_class", "DHCP")) == "DHCP"
                and str(row.get("option_number", "")) == str(parameter.option_number)]
    return [row for row in scalars
            if row.get("object_type") == parameter.object_type
            and row.get("parameter") == parameter.parameter]


def _is_inheritance_wrapper(value: Any) -> bool:
    return isinstance(value, dict) and ("inherited" in value or "multisource" in value)


def _authoritative_effective_option_keys(record: dict[str, Any]) -> set[tuple[str, str]] | None:
    """Return option keys only when the effective WAPI option shape is authoritative."""
    value = record.get("options")
    if not isinstance(value, list) or not value:
        return None
    keys: set[tuple[str, str]] = set()
    for group in value:
        if not _is_inheritance_wrapper(group):
            return None
        if "values" not in group:
            if group.get("source") == "NOT_DEFINED":
                values = []
            else:
                return None
        else:
            values = group.get("values")
        if not isinstance(values, list):
            return None
        for option in values:
            if not isinstance(option, dict):
                return None
            vendor = str(option.get("vendor_class") or "DHCP")
            number = str(option.get("num", option.get("name", "")))
            keys.add((vendor, number))
    return keys


def _profile_evidence_counts(spec: ProfileInputSpec, rows: list[dict[str, Any]],
                             population_keys: set[tuple[str, str]],
                             effective_by_key: dict[tuple[str, str], dict[str, Any]]) -> tuple[int, int]:
    """Count functional values independently from inheritance/source metadata.

    Source level/reference/configured_here/inherited stay preserved in normalized
    evidence, but they do not make identical effective values different for a
    functional profile. Any multisource observation remains conservative.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = normalized_object_key(row)
        if key in population_keys:
            grouped[key].append(row)

    parameter = next(item for item in PARAMETER_SPECS if item.key == spec.source_parameter_id)
    confirmed = 0
    explicit_not_configured = 0
    for key in population_keys:
        object_rows = grouped.get(key, [])
        statuses = {row.get("status") for row in object_rows}
        has_multisource = any(row.get("multisource") is True for row in object_rows)
        complete = [row for row in object_rows
                    if row.get("status") == "COMPLETE"
                    and row.get("multisource") is not True
                    and row.get("effective_value") is not None]
        effective_values = {
            json.dumps(row.get("effective_value"), sort_keys=True, default=str)
            for row in complete
        }
        if not has_multisource and len(effective_values) == 1 and "NOT_CONFIGURED" not in statuses:
            confirmed += 1
            continue
        if object_rows and statuses == {"NOT_CONFIGURED"}:
            explicit_not_configured += 1
            continue

        # Absence is evidence only for a recognized authoritative effective
        # options structure. It remains local to profile-readiness accounting;
        # normalized technical evidence is not polluted with synthetic rows.
        if parameter.source == "option" and parameter.option_number is not None:
            effective = effective_by_key.get(key)
            authoritative = _authoritative_effective_option_keys(effective or {})
            target = ("DHCP", str(parameter.option_number))
            if authoritative is not None and target not in authoritative:
                explicit_not_configured += 1
    return confirmed, explicit_not_configured


def _authoritative_scalar_external_keys(rows: list[dict[str, Any]],
                                        external_keys: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Keep externally managed ranges only when scalar evidence is authoritative.

    COMPLETE or explicit NOT_CONFIGURED evidence proves that WAPI exposed a
    parameter state for this object. PARTIAL/unresolved msserver:dhcp source
    references do not expand the applicable denominator.
    """
    authoritative: set[tuple[str, str]] = set()
    for row in rows:
        key = normalized_object_key(row)
        if key not in external_keys:
            continue
        if row.get("status") == "NOT_CONFIGURED":
            authoritative.add(key)
        elif row.get("status") == "COMPLETE" and row.get("effective_value") is not None:
            authoritative.add(key)
    return authoritative


def _scope_profile_metrics(spec: ProfileInputSpec, source: dict[str, Any],
                           results: list[CollectionResult], scalars: list[dict[str, Any]],
                           options: list[dict[str, Any]]) -> dict[str, Any]:
    object_type = spec.scope.lower()
    rows = _profile_parameter_rows(spec, scalars, options)
    parameter = next(item for item in PARAMETER_SPECS if item.key == spec.source_parameter_id)

    if spec.scope == "Network":
        population_keys = set(dhcp_relevant_networks(results))
        query_keys = effective_network_keys(results)
        basis = NETWORK_POPULATION_BASIS
    elif parameter.source == "option":
        population_keys = dhcp_associated_range_keys(results)
        query_keys = effective_range_keys(results)
        basis = RANGE_DHCP_ASSOCIATED_BASIS
    else:
        base = infoblox_managed_range_keys(results)
        external = ms_server_range_keys(results)
        authoritative_external = _authoritative_scalar_external_keys(rows, external)
        population_keys = base | authoritative_external
        query_keys = effective_range_keys(results)
        basis = RANGE_INFOBLOX_MANAGED_BASIS
        if authoritative_external:
            basis += "+AUTHORITATIVE_MS_SERVER"

    query_objects = len(population_keys & query_keys)
    population = len(population_keys)
    source_population = source.get("Population Objects")
    excluded = (max(source_population - population, 0)
                if type(source_population) is int else None)
    effective_by_key = effective_records_by_key(results, object_type)
    confirmed, not_configured = _profile_evidence_counts(
        spec, rows, population_keys, effective_by_key
    )
    resolved = confirmed + not_configured
    unresolved = max(population - resolved, 0)
    collection = source.get("Collection Status")
    field_status = source.get("Required Field Status")
    source_evidence = source.get("Evidence Status")
    if field_status == "NOT_EXPOSED_BY_WAPI":
        evidence_status = "NOT_EXPOSED_BY_WAPI"
    elif collection != "COMPLETE":
        evidence_status = source_evidence or "PARTIAL"
    elif unresolved == 0 and population > 0:
        evidence_status = "NOT_CONFIGURED" if confirmed == 0 and not_configured == population else "COMPLETE"
    elif population == 0:
        evidence_status = source_evidence or "INSUFFICIENT_DATA"
    else:
        evidence_status = "PARTIAL"
    return {
        "Population Basis": basis,
        "Source Population Objects": source_population,
        "Population Objects": population,
        "Excluded By Applicability": excluded,
        "Query Evidence Objects": query_objects,
        "Query Coverage %": _percent(query_objects, population),
        "Confirmed Objects": confirmed,
        "Confirmed Value %": _percent(confirmed, population),
        "Explicit Not Configured": not_configured,
        "Resolved Evidence %": _percent(resolved, population),
        "Unresolved Objects": unresolved,
        "Unresolved %": _percent(unresolved, population),
        "Evidence Status": evidence_status,
    }

def build_profile_readiness(standardization: Iterable[dict[str, Any]],
                            specs: Iterable[ProfileInputSpec] = PROFILE_INPUT_SPECS, *,
                            results: list[CollectionResult] | None = None,
                            scalars: list[dict[str, Any]] | None = None,
                            options: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Project scoped evidence into candidate inputs for future profile discovery.

    When object-level evidence is supplied, Network inputs use an evidence-based
    DHCP-relevant candidate population rather than every IPAM Network object.
    Range inputs continue to use the complete Range population.
    """
    candidates = tuple(specs)
    validate_profile_inputs(candidates)
    wanted = {spec.source_parameter_id for spec in candidates}
    indexed: dict[str, dict[str, Any]] = {}
    for source_row in standardization:
        parameter_id = source_row.get("Parameter ID")
        if parameter_id not in wanted:
            continue
        if parameter_id in indexed:
            raise ValueError(f"Duplicate Standardization Parameter ID: {parameter_id}")
        indexed[parameter_id] = source_row
    parameters = {parameter.key: parameter for parameter in PARAMETER_SPECS}
    object_level_available = results is not None and scalars is not None and options is not None
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
            "Population Basis": (NETWORK_POPULATION_BASIS if spec.scope == "Network" and object_level_available
                                 else RANGE_DHCP_ASSOCIATED_BASIS if spec.scope == "Range" and object_level_available
                                 else "SCOPED_STANDARDIZATION"),
            "Source Population Objects": (source or {}).get("Population Objects"),
            **{header: (source or {}).get(header) for header in _EVIDENCE_HEADERS},
        }
        if source is None:
            row.update({"Required Field": parameter.required_field, "Required Field Status": "UNKNOWN",
                        "Collection Status": "UNKNOWN", "Evidence Status": "INSUFFICIENT_DATA",
                        "Readiness": "NOT_READY", "Readiness Reason": "Standardization evidence unavailable"})
        else:
            if object_level_available:
                row.update(_scope_profile_metrics(spec, source, results or [], scalars or [], options or []))
            if (spec.semantic_role == "COMPOSITE_LATER"
                    and not (row.get("Population Objects") == 0
                             and row.get("Source Population Objects") == 0)):
                row["Readiness"] = "DEFERRED"
                row["Readiness Reason"] = "Composite semantics deferred; source evidence retained for review"
            else:
                row["Readiness"], row["Readiness Reason"] = _classify(row)
        output.append(row)
    return output

def profile_readiness_summary(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Count candidate inputs, excluding semantic deferrals and empty scopes from the rate."""
    counts: dict[str, Counter[str]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["Profile"], row["Input Key"])
        if key in seen:
            raise ValueError(f"Duplicate profile readiness input: {key[0]} / {key[1]}")
        seen.add(key)
        state = row["Readiness"]
        if state not in {"READY", "CONDITIONAL", "NOT_READY", "DEFERRED", "NOT_APPLICABLE"}:
            raise ValueError(f"Unknown profile readiness state: {state}")
        counts.setdefault(row["Profile"], Counter())[state] += 1
    output = []
    for profile in sorted(counts):
        states = counts[profile]
        total = sum(states.values())
        applicable = total - states["NOT_APPLICABLE"] - states["DEFERRED"]
        output.append({
            "Profile": profile, "Candidate Inputs": total, "Applicable Inputs": applicable,
            **{state: states[state] for state in
               ("READY", "CONDITIONAL", "NOT_READY", "DEFERRED", "NOT_APPLICABLE")},
            "Ready Input %": round(states["READY"] * 100.0 / applicable, 1) if applicable else None,
        })
    return output


validate_profile_inputs()

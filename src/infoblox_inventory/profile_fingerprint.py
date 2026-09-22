"""Deterministic profile usefulness and exact functional fingerprints.

This layer groups observed effective configuration. It does not infer an
approved standard, compliance state, semantic business role, or remediation.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import ipaddress
import json
import re
from typing import Any

from .models import CollectionResult
from .profile_population import (
    NETWORK_POPULATION_BASIS,
    RANGE_DHCP_ASSOCIATED_BASIS,
    RANGE_INFOBLOX_MANAGED_BASIS,
    RANGE_SEGMENT_FAILOVER,
    RANGE_SEGMENT_MEMBER,
    RANGE_SEGMENT_MS_SERVER,
    RANGE_SEGMENT_NONE,
    RANGE_SEGMENT_OTHER,
    RANGE_SEGMENT_UNKNOWN,
    all_range_keys,
    dhcp_associated_range_keys,
    dhcp_relevant_networks,
    effective_records_by_key,
    infoblox_managed_range_keys,
    ms_server_range_keys,
    normalized_object_key,
    object_key,
    range_association_segment,
)
from .profile_readiness import (
    PROFILE_INPUT_SPECS,
    ProfileInputSpec,
    _authoritative_effective_option_keys,
    _authoritative_scalar_external_keys,
    _profile_parameter_rows,
)
from .standardization import PARAMETER_SPECS


FINGERPRINT_SCHEMA_VERSION = 1

NETWORK_CORE_PARAMETER_IDS = (
    "dhcp.lease_time.network",
    "dhcp.dns_servers.network",
    "dhcp.domain_name.network",
    "dhcp.router.network",
)
RANGE_CORE_PARAMETER_IDS = (
    "dhcp.lease_time.range",
    "dhcp.dns_servers.range",
    "dhcp.domain_name.range",
    "dhcp.router.range",
)
CORE_PARAMETER_IDS = set(NETWORK_CORE_PARAMETER_IDS) | set(RANGE_CORE_PARAMETER_IDS)

PROFILE_USEFULNESS_HEADERS = [
    "Profile", "Input Key", "Input", "Parameter ID", "Scope", "Semantic Role",
    "Population Basis", "Population Objects", "Excluded By Applicability",
    "Resolved Objects", "Resolved %", "Value Objects", "Explicit Not Configured",
    "Unresolved Objects", "Unresolved %", "Distinct Resolved States",
    "Distinct Configured Values", "Dominant State", "Dominant State Count",
    "Dominant State % Population", "Dominant State % Resolved",
    "Invariant Among Resolved", "Core Fingerprint v1", "Observed Role", "Readiness",
]

PROFILE_DISCOVERY_HEADERS = [
    "Profile Type", "Applicable Objects", "Profiled Objects", "Profiled %",
    "Unresolved Objects", "Unresolved Association Objects", "Not Applicable Objects", "Distinct Profiles",
    "Top-1 Share %", "Top-3 Share %", "Profiles for 80%", "Profiles for 90%",
    "Profiles for 95%", "Singleton Profiles",
]

PROFILE_HEADERS = [
    "Profile Type", "Schema Version", "Profile Rank", "Fingerprint ID",
    "Full Fingerprint SHA256", "Profiled Objects", "Share of Profiled %",
    "Share of Applicable %", "Association Family", "Lease Time", "DNS Servers",
    "Domain Name", "Gateway Convention", "Canonical Payload",
    "Context Summary", "Overlay Variable Inputs", "Overlay Unresolved Inputs",
    "Feature Overlay Summary",
]

PROFILE_OBJECT_HEADERS = [
    "Profile Type", "Grid", "Object Type", "Object", "Object Ref", "Network View",
    "Parent Network", "Association Family", "Profile Status", "Fingerprint ID",
    "Profile Rank", "Missing Inputs", "Lease Time", "DNS Servers", "Domain Name",
    "Gateway Convention",
]


def _parameter(spec: ProfileInputSpec):
    return next(item for item in PARAMETER_SPECS if item.key == spec.source_parameter_id)


def _percent(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100.0 / denominator, 1) if denominator else None


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _state(status: str, value: Any = None) -> dict[str, Any]:
    if status == "VALUE":
        return {"status": "VALUE", "value": value}
    return {"status": status}


def _state_signature(state: dict[str, Any]) -> str:
    return _canonical(state)


def _state_display(state: dict[str, Any]) -> str:
    status = state.get("status")
    if status != "VALUE":
        return str(status or "UNRESOLVED")
    value = state.get("value")
    if value == "":
        return 'VALUE:""'
    return "VALUE:" + _canonical(value)


def _state_cell(state: dict[str, Any]) -> Any:
    status = state.get("status")
    if status == "NOT_CONFIGURED":
        return "NOT_CONFIGURED"
    if status != "VALUE":
        return str(status or "UNRESOLVED")
    value = state.get("value")
    if value == "":
        return "EMPTY_STRING"
    if isinstance(value, (dict, list)):
        return _canonical(value)
    return value


def _raw_records_by_key(results: list[CollectionResult], object_type: str) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        object_key(result.grid, record): record
        for result in results
        for record in result.records.get(object_type, [])
    }


def _all_network_keys(results: list[CollectionResult]) -> set[tuple[str, str]]:
    return {
        object_key(result.grid, record)
        for result in results
        for record in result.records.get("network", [])
    }


def _population_for_spec(
    spec: ProfileInputSpec,
    results: list[CollectionResult],
    rows: list[dict[str, Any]],
) -> tuple[str, set[tuple[str, str]], int]:
    """Return population basis, applicable object keys and excluded count."""
    parameter = _parameter(spec)
    if spec.scope == "Network":
        source = _all_network_keys(results)
        population = set(dhcp_relevant_networks(results))
        return NETWORK_POPULATION_BASIS, population, max(len(source) - len(population), 0)

    source = all_range_keys(results)
    if parameter.source == "option":
        population = dhcp_associated_range_keys(results)
        return RANGE_DHCP_ASSOCIATED_BASIS, population, max(len(source) - len(population), 0)

    base = infoblox_managed_range_keys(results)
    external = ms_server_range_keys(results)
    authoritative_external = _authoritative_scalar_external_keys(rows, external)
    population = base | authoritative_external
    basis = RANGE_INFOBLOX_MANAGED_BASIS
    if authoritative_external:
        basis += "+AUTHORITATIVE_MS_SERVER"
    return basis, population, max(len(source) - len(population), 0)


def _functional_states(
    spec: ProfileInputSpec,
    rows: list[dict[str, Any]],
    population_keys: set[tuple[str, str]],
    effective_by_key: dict[tuple[str, str], dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Resolve one functional state per object using Profile Readiness semantics."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = normalized_object_key(row)
        if key in population_keys:
            grouped[key].append(row)

    parameter = _parameter(spec)
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for key in population_keys:
        object_rows = grouped.get(key, [])
        statuses = {row.get("status") for row in object_rows}
        has_multisource = any(row.get("multisource") is True for row in object_rows)
        complete = [
            row for row in object_rows
            if row.get("status") == "COMPLETE"
            and row.get("multisource") is not True
            and row.get("effective_value") is not None
        ]
        values: dict[str, Any] = {}
        for row in complete:
            value = row.get("effective_value")
            values.setdefault(_canonical(value), value)

        if not has_multisource and len(values) == 1 and "NOT_CONFIGURED" not in statuses:
            output[key] = _state("VALUE", next(iter(values.values())))
            continue
        if object_rows and statuses == {"NOT_CONFIGURED"}:
            output[key] = _state("NOT_CONFIGURED")
            continue

        if parameter.source == "option" and parameter.option_number is not None:
            effective = effective_by_key.get(key)
            authoritative = _authoritative_effective_option_keys(effective or {})
            target = ("DHCP", str(parameter.option_number))
            if authoritative is not None and target not in authoritative:
                output[key] = _state("NOT_CONFIGURED")
                continue
        output[key] = _state("UNRESOLVED")
    return output


def _gateway_convention(value_state: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    if value_state.get("status") == "NOT_CONFIGURED":
        return _state("NOT_CONFIGURED")
    if value_state.get("status") != "VALUE":
        return _state("UNRESOLVED")

    value = value_state.get("value")
    if not isinstance(value, str):
        return _state("VALUE", "INVALID_VALUE")
    if value == "":
        return _state("VALUE", "EMPTY_VALUE")

    tokens = [token for token in re.split(r"[,;\s]+", value.strip()) if token]
    if not tokens:
        return _state("VALUE", "EMPTY_VALUE")
    if len(tokens) > 1:
        return _state("VALUE", "MULTIPLE_ROUTERS")
    try:
        address = ipaddress.ip_address(tokens[0])
    except ValueError:
        return _state("VALUE", "INVALID_VALUE")

    network_text = (raw or {}).get("network")
    if not network_text:
        return _state("VALUE", "NO_PARENT_NETWORK")
    try:
        network = ipaddress.ip_network(str(network_text), strict=False)
    except ValueError:
        return _state("VALUE", "NO_PARENT_NETWORK")
    if address.version != network.version or address not in network:
        return _state("VALUE", "OUTSIDE_SUBNET")

    if network.version == 4:
        if network.prefixlen <= 30:
            first = ipaddress.ip_address(int(network.network_address) + 1)
            last = ipaddress.ip_address(int(network.broadcast_address) - 1)
        elif network.prefixlen == 31:
            first, last = network.network_address, network.broadcast_address
        else:
            first = last = network.network_address
    else:
        first = (ipaddress.ip_address(int(network.network_address) + 1)
                 if network.num_addresses > 1 else network.network_address)
        last = ipaddress.ip_address(int(network.network_address) + network.num_addresses - 1)

    if address == first:
        return _state("VALUE", "FIRST_USABLE")
    if address == last:
        return _state("VALUE", "LAST_USABLE")
    return _state("VALUE", f"HOST_OFFSET_{int(address) - int(network.network_address)}")


def _input_states(
    spec: ProfileInputSpec,
    results: list[CollectionResult],
    scalars: list[dict[str, Any]],
    options: list[dict[str, Any]],
) -> tuple[str, set[tuple[str, str]], int, dict[tuple[str, str], dict[str, Any]]]:
    rows = _profile_parameter_rows(spec, scalars, options)
    basis, population, excluded = _population_for_spec(spec, results, rows)
    effective = effective_records_by_key(results, spec.scope.lower())
    states = _functional_states(spec, rows, population, effective)
    if spec.source_parameter_id.startswith("dhcp.router."):
        raw_by_key = _raw_records_by_key(results, spec.scope.lower())
        states = {
            key: _gateway_convention(state, raw_by_key.get(key))
            for key, state in states.items()
        }
    return basis, population, excluded, states


def _readiness_map(readiness: list[dict[str, Any]] | None) -> dict[str, str]:
    return {
        str(row.get("Parameter ID")): str(row.get("Readiness"))
        for row in (readiness or [])
        if row.get("Parameter ID")
    }


def build_profile_usefulness(
    results: list[CollectionResult],
    scalars: list[dict[str, Any]],
    options: list[dict[str, Any]],
    readiness: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Describe discriminative evidence without producing a weighted score."""
    ready = _readiness_map(readiness)
    output: list[dict[str, Any]] = []
    for spec in PROFILE_INPUT_SPECS:
        basis, population, excluded, states = _input_states(spec, results, scalars, options)
        resolved_states = [
            state for state in states.values()
            if state.get("status") in {"VALUE", "NOT_CONFIGURED"}
        ]
        value_states = [state for state in resolved_states if state.get("status") == "VALUE"]
        not_configured = sum(state.get("status") == "NOT_CONFIGURED" for state in resolved_states)
        unresolved = max(len(population) - len(resolved_states), 0)

        resolved_counter = Counter(_state_signature(state) for state in resolved_states)
        value_counter = Counter(_canonical(state.get("value")) for state in value_states)
        dominant_signature = ""
        dominant_count = 0
        if resolved_counter:
            dominant_signature, dominant_count = sorted(
                resolved_counter.items(), key=lambda item: (-item[1], item[0])
            )[0]
        dominant_state = (
            _state_display(json.loads(dominant_signature)) if dominant_signature else ""
        )

        core = spec.source_parameter_id in CORE_PARAMETER_IDS
        if spec.semantic_role == "COMPOSITE_LATER":
            observed_role = "DEFERRED_COMPOSITE"
        elif core:
            observed_role = "CORE_FINGERPRINT_V1"
        elif not resolved_states:
            observed_role = "NO_RESOLVED_EVIDENCE"
        elif len(resolved_counter) == 1:
            observed_role = "INVARIANT_AMONG_RESOLVED"
        else:
            observed_role = "VARIABLE_OVERLAY"

        output.append({
            "Profile": spec.profile,
            "Input Key": spec.input_key,
            "Input": spec.label,
            "Parameter ID": spec.source_parameter_id,
            "Scope": spec.scope,
            "Semantic Role": spec.semantic_role,
            "Population Basis": basis,
            "Population Objects": len(population),
            "Excluded By Applicability": excluded,
            "Resolved Objects": len(resolved_states),
            "Resolved %": _percent(len(resolved_states), len(population)),
            "Value Objects": len(value_states),
            "Explicit Not Configured": not_configured,
            "Unresolved Objects": unresolved,
            "Unresolved %": _percent(unresolved, len(population)),
            "Distinct Resolved States": len(resolved_counter),
            "Distinct Configured Values": len(value_counter),
            "Dominant State": dominant_state,
            "Dominant State Count": dominant_count,
            "Dominant State % Population": _percent(dominant_count, len(population)),
            "Dominant State % Resolved": _percent(dominant_count, len(resolved_states)),
            "Invariant Among Resolved": bool(resolved_states) and len(resolved_counter) == 1,
            "Core Fingerprint v1": "YES" if core else "NO",
            "Observed Role": observed_role,
            "Readiness": ready.get(spec.source_parameter_id, ""),
        })
    return output


def _spec_by_parameter(parameter_id: str) -> ProfileInputSpec:
    return next(spec for spec in PROFILE_INPUT_SPECS if spec.source_parameter_id == parameter_id)


def _core_state_maps(
    scope: str,
    results: list[CollectionResult],
    scalars: list[dict[str, Any]],
    options: list[dict[str, Any]],
) -> dict[str, dict[tuple[str, str], dict[str, Any]]]:
    parameter_ids = NETWORK_CORE_PARAMETER_IDS if scope == "Network" else RANGE_CORE_PARAMETER_IDS
    output: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for parameter_id in parameter_ids:
        spec = _spec_by_parameter(parameter_id)
        _basis, _population, _excluded, states = _input_states(spec, results, scalars, options)
        output[spec.input_key] = states
    return output


def _fingerprint_payload(
    profile_type: str,
    fields: dict[str, dict[str, Any]],
    association_family: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "profile_type": profile_type.lower(),
        "fields": fields,
    }
    if association_family:
        payload["association_family"] = association_family
    return payload


def _fingerprint_id(profile_type: str, payload: dict[str, Any]) -> tuple[str, str]:
    digest = sha256(_canonical(payload).encode("utf-8")).hexdigest()
    prefix = "NET" if profile_type == "Network" else "RNG"
    return f"{prefix}-FP{FINGERPRINT_SCHEMA_VERSION}-{digest[:12]}", digest


def _object_label(scope: str, raw: dict[str, Any]) -> str:
    if scope == "Network":
        return str(raw.get("network") or raw.get("name") or raw.get("_ref") or "")
    start = raw.get("start_addr")
    end = raw.get("end_addr")
    if start or end:
        return f"{start or ''}-{end or ''}"
    return str(raw.get("name") or raw.get("_ref") or "")


def _context_summary(
    scope: str,
    keys: set[tuple[str, str]],
    raw_by_key: dict[tuple[str, str], dict[str, Any]],
    network_reasons: dict[tuple[str, str], set[str]],
) -> str:
    views = Counter(str((raw_by_key.get(key) or {}).get("network_view") or "default") for key in keys)
    payload: dict[str, Any] = {"network_view": dict(sorted(views.items()))}
    if scope == "Network":
        signatures = Counter(
            "+".join(sorted(network_reasons.get(key, set()))) or "NO_SIGNAL"
            for key in keys
        )
        payload["dhcp_relevance_signals"] = dict(sorted(signatures.items()))
    return _canonical(payload)


def _overlay_summary(
    scope: str,
    profile_keys: set[tuple[str, str]],
    all_states: dict[str, tuple[set[tuple[str, str]], dict[tuple[str, str], dict[str, Any]]]],
) -> tuple[int, int, str]:
    core_ids = set(NETWORK_CORE_PARAMETER_IDS if scope == "Network" else RANGE_CORE_PARAMETER_IDS)
    payload: dict[str, Any] = {}
    variable = 0
    unresolved_inputs = 0
    for spec in PROFILE_INPUT_SPECS:
        if spec.scope != scope or spec.source_parameter_id in core_ids:
            continue
        population, states = all_states[spec.source_parameter_id]
        distribution = Counter()
        for key in profile_keys:
            if key not in population:
                distribution["NOT_APPLICABLE"] += 1
            else:
                state = states.get(key, _state("UNRESOLVED"))
                distribution[_state_display(state)] += 1
        if len(distribution) > 1:
            variable += 1
        if distribution.get("UNRESOLVED", 0):
            unresolved_inputs += 1
        payload[spec.input_key] = dict(sorted(distribution.items()))
    return variable, unresolved_inputs, _canonical(payload)


def _profiles_to_cover(counts: list[int], total: int, threshold: float) -> int | None:
    if not counts or total <= 0:
        return None
    cumulative = 0
    for index, count in enumerate(counts, start=1):
        cumulative += count
        if cumulative * 100.0 / total >= threshold:
            return index
    return len(counts)


def build_profile_discovery(
    results: list[CollectionResult],
    scalars: list[dict[str, Any]],
    options: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build exact functional profiles and object assignments.

    Returns (discovery summary rows, profile rows, object assignment rows).
    """
    raw_network = _raw_records_by_key(results, "network")
    raw_range = _raw_records_by_key(results, "range")
    relevant_networks = dhcp_relevant_networks(results)
    network_population = set(relevant_networks)
    range_population = dhcp_associated_range_keys(results)

    all_states: dict[str, tuple[set[tuple[str, str]], dict[tuple[str, str], dict[str, Any]]]] = {}
    for spec in PROFILE_INPUT_SPECS:
        _basis, population, _excluded, states = _input_states(spec, results, scalars, options)
        all_states[spec.source_parameter_id] = (population, states)

    summaries: list[dict[str, Any]] = []
    profile_rows: list[dict[str, Any]] = []
    object_rows: list[dict[str, Any]] = []

    for scope, population, raw_by_key in (
        ("Network", network_population, raw_network),
        ("Range", range_population, raw_range),
    ):
        core_maps = _core_state_maps(scope, results, scalars, options)
        grouped: dict[str, dict[str, Any]] = {}
        unresolved_count = 0

        for key in sorted(population):
            raw = raw_by_key.get(key, {})
            association = ""
            if scope == "Range":
                association, _raw_association = range_association_segment(raw)

            fields = {
                "lease_time": core_maps["lease_time"].get(key, _state("UNRESOLVED")),
                "dns_servers": core_maps["dns_servers"].get(key, _state("UNRESOLVED")),
                "domain_name": core_maps["domain_name"].get(key, _state("UNRESOLVED")),
                "gateway_convention": core_maps["gateway_convention"].get(key, _state("UNRESOLVED")),
            }
            missing = [name for name, state in fields.items()
                       if state.get("status") not in {"VALUE", "NOT_CONFIGURED"}]

            fingerprint = ""
            rank: int | str = ""
            profile_status = "PROFILED"
            if missing:
                profile_status = "UNRESOLVED_PROFILE_INPUTS"
                unresolved_count += 1
            else:
                payload = _fingerprint_payload(scope, fields, association)
                fingerprint, digest = _fingerprint_id(scope, payload)
                item = grouped.setdefault(fingerprint, {
                    "digest": digest,
                    "payload": payload,
                    "keys": set(),
                    "fields": fields,
                    "association": association,
                })
                item["keys"].add(key)

            object_rows.append({
                "Profile Type": scope,
                "Grid": key[0],
                "Object Type": scope.lower(),
                "Object": _object_label(scope, raw),
                "Object Ref": raw.get("_ref", key[1]),
                "Network View": raw.get("network_view", ""),
                "Parent Network": raw.get("network", "") if scope == "Range" else raw.get("network", ""),
                "Association Family": association,
                "Profile Status": profile_status,
                "Fingerprint ID": fingerprint,
                "Profile Rank": rank,
                "Missing Inputs": ", ".join(missing),
                "Lease Time": _state_cell(fields["lease_time"]),
                "DNS Servers": _state_cell(fields["dns_servers"]),
                "Domain Name": _state_cell(fields["domain_name"]),
                "Gateway Convention": _state_cell(fields["gateway_convention"]),
            })

        ordered_profiles = sorted(
            grouped.items(),
            key=lambda item: (-len(item[1]["keys"]), item[0]),
        )
        rank_by_fingerprint = {
            fingerprint: rank
            for rank, (fingerprint, _item) in enumerate(ordered_profiles, start=1)
        }
        profiled = sum(len(item["keys"]) for _fingerprint, item in ordered_profiles)
        counts = [len(item["keys"]) for _fingerprint, item in ordered_profiles]

        for fingerprint, item in ordered_profiles:
            keys = item["keys"]
            fields = item["fields"]
            variable, overlay_unresolved, overlay = _overlay_summary(
                scope, keys, all_states
            )
            profile_rows.append({
                "Profile Type": scope,
                "Schema Version": FINGERPRINT_SCHEMA_VERSION,
                "Profile Rank": rank_by_fingerprint[fingerprint],
                "Fingerprint ID": fingerprint,
                "Full Fingerprint SHA256": item["digest"],
                "Profiled Objects": len(keys),
                "Share of Profiled %": _percent(len(keys), profiled),
                "Share of Applicable %": _percent(len(keys), len(population)),
                "Association Family": item["association"],
                "Lease Time": _state_cell(fields["lease_time"]),
                "DNS Servers": _state_cell(fields["dns_servers"]),
                "Domain Name": _state_cell(fields["domain_name"]),
                "Gateway Convention": _state_cell(fields["gateway_convention"]),
                "Canonical Payload": _canonical(item["payload"]),
                "Context Summary": _context_summary(
                    scope, keys, raw_by_key, relevant_networks
                ),
                "Overlay Variable Inputs": variable,
                "Overlay Unresolved Inputs": overlay_unresolved,
                "Feature Overlay Summary": overlay,
            })

        for row in object_rows:
            if row["Profile Type"] == scope and row["Fingerprint ID"]:
                row["Profile Rank"] = rank_by_fingerprint[row["Fingerprint ID"]]

        not_applicable = 0
        unresolved_association = 0
        if scope == "Range":
            for key, raw in sorted(raw_range.items()):
                if key in range_population:
                    continue
                association, _raw_association = range_association_segment(raw)
                if association == RANGE_SEGMENT_NONE:
                    status = "NOT_APPLICABLE_TO_DHCP_PROFILE"
                    not_applicable += 1
                else:
                    status = "UNRESOLVED_ASSOCIATION"
                    unresolved_association += 1
                object_rows.append({
                    "Profile Type": scope,
                    "Grid": key[0],
                    "Object Type": "range",
                    "Object": _object_label(scope, raw),
                    "Object Ref": raw.get("_ref", key[1]),
                    "Network View": raw.get("network_view", ""),
                    "Parent Network": raw.get("network", ""),
                    "Association Family": association,
                    "Profile Status": status,
                    "Fingerprint ID": "",
                    "Profile Rank": "",
                    "Missing Inputs": "association_family" if status == "UNRESOLVED_ASSOCIATION" else "",
                    "Lease Time": "",
                    "DNS Servers": "",
                    "Domain Name": "",
                    "Gateway Convention": "",
                })

        summaries.append({
            "Profile Type": scope,
            "Applicable Objects": len(population),
            "Profiled Objects": profiled,
            "Profiled %": _percent(profiled, len(population)),
            "Unresolved Objects": unresolved_count,
            "Unresolved Association Objects": unresolved_association,
            "Not Applicable Objects": not_applicable,
            "Distinct Profiles": len(ordered_profiles),
            "Top-1 Share %": _percent(sum(counts[:1]), profiled),
            "Top-3 Share %": _percent(sum(counts[:3]), profiled),
            "Profiles for 80%": _profiles_to_cover(counts, profiled, 80.0),
            "Profiles for 90%": _profiles_to_cover(counts, profiled, 90.0),
            "Profiles for 95%": _profiles_to_cover(counts, profiled, 95.0),
            "Singleton Profiles": sum(count == 1 for count in counts),
        })

    profile_rows.sort(key=lambda row: (
        str(row["Profile Type"]), int(row["Profile Rank"]), str(row["Fingerprint ID"])
    ))
    object_rows.sort(key=lambda row: (
        str(row["Profile Type"]), str(row["Grid"]), str(row["Object Ref"])
    ))
    summaries.sort(key=lambda row: str(row["Profile Type"]))
    return summaries, profile_rows, object_rows

"""Deterministic profile usefulness and exact fingerprint discovery.

This layer is descriptive only. It groups resolved current-state functional
configuration; it never infers an approved standard, compliance, or remediation.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
from ipaddress import ip_address, ip_network
import json
from typing import Any

from .models import CollectionResult
from .profile_population import (
    RANGE_SEGMENT_FAILOVER, RANGE_SEGMENT_MEMBER, RANGE_SEGMENT_MS_SERVER,
    RANGE_SEGMENT_NONE, RANGE_SEGMENT_OTHER, RANGE_SEGMENT_UNKNOWN,
    dhcp_associated_range_keys, dhcp_profile_networks, object_key,
    range_association_segment,
)
from .profile_readiness import (
    PROFILE_INPUT_SPECS, ProfileInputSpec, profile_object_states,
    profile_parameter_rows, profile_population_for_spec,
)


CORE_INPUT_KEYS = ("lease_time", "dns_servers", "domain_name", "gateway_convention")
PROFILE_SCHEMA_VERSION = 1
PROFILE_HASH_LENGTH = 12

PROFILE_USEFULNESS_HEADERS = [
    "Profile", "Input Key", "Input", "Parameter ID", "Scope", "Semantic Role",
    "Fingerprint Role", "Population Basis", "Population Objects", "Resolved Objects",
    "Resolved %", "Unresolved Objects", "Unresolved %", "Distinct Resolved States",
    "Distinct Configured Values", "Explicit Not Configured", "Dominant State",
    "Dominant State Count", "Dominant % Population", "Dominant % Resolved",
    "Invariant Among Resolved", "Readiness",
]

PROFILE_FINGERPRINT_HEADERS = [
    "Profile", "Fingerprint ID", "Display Rank", "Association Family", "Object Count",
    "Share of Profiled %", "Share of Applicable %", "Lease Time", "DNS Servers",
    "Domain Name", "Gateway Convention", "Canonical Payload", "Full SHA256",
    "Feature Overlay Distributions",
]

PROFILE_ASSIGNMENT_HEADERS = [
    "Profile", "Grid", "Scope", "Object Ref", "Object", "Network View",
    "Association Family", "Population Status", "Fingerprint ID", "Display Rank",
    "Missing Core Inputs", "Network Relevance Reasons", "Lease Time", "DNS Servers",
    "Domain Name", "Gateway Convention",
]

PROFILE_KPI_HEADERS = [
    "Profile", "Applicable Objects", "Profiled Objects", "Profiled %",
    "Unresolved Profile Objects", "Unresolved %", "Distinct Profiles", "Top-1 Share of Profiled %",
    "Top-3 Share of Profiled %", "Profiles for 80%", "Profiles for 90%", "Profiles for 95%",
    "Singleton Profiles",
]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _state_label(state: dict[str, Any]) -> str:
    status = str(state.get("status") or "UNRESOLVED")
    if status == "VALUE":
        return f"VALUE:{_json(state.get('value'))}"
    return status


def _display_state(state: dict[str, Any]) -> Any:
    status = state.get("status")
    if status == "VALUE":
        value = state.get("value")
        if isinstance(value, str) and not value.strip():
            return "EMPTY_VALUE"
        return value
    return status


def _raw_records_by_key(results: list[CollectionResult], object_type: str) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        object_key(result.grid, record): record
        for result in results
        for record in result.records.get(object_type, [])
    }


def _normalized_values(value: Any) -> list[str] | None:
    if isinstance(value, (list, tuple)):
        values = [str(item).strip() for item in value]
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        values = [part.strip() for part in stripped.split(",")]
    elif value is None:
        return []
    else:
        values = [str(value).strip()]
    return values


def derive_gateway_convention(state: dict[str, Any], parent_network: Any) -> dict[str, Any]:
    """Convert router evidence to a topology-relative convention."""
    status = state.get("status")
    if status == "NOT_CONFIGURED":
        return {"status": "NOT_CONFIGURED", "value": None}
    if status != "VALUE":
        return {"status": "UNRESOLVED", "value": None}

    values = _normalized_values(state.get("value"))
    if values is None:
        return {"status": "VALUE", "value": "INVALID_VALUE"}
    if not values or all(not item for item in values):
        return {"status": "VALUE", "value": "EMPTY_VALUE"}
    if len(values) != 1:
        return {"status": "VALUE", "value": "MULTIPLE_ROUTERS"}

    try:
        router = ip_address(values[0])
    except ValueError:
        return {"status": "VALUE", "value": "INVALID_VALUE"}
    if not parent_network:
        return {"status": "UNRESOLVED", "value": "NO_PARENT_NETWORK"}
    try:
        network = ip_network(str(parent_network), strict=False)
    except ValueError:
        return {"status": "UNRESOLVED", "value": "NO_PARENT_NETWORK"}
    if router.version != network.version or router not in network:
        return {"status": "VALUE", "value": "OUTSIDE_SUBNET"}

    if network.num_addresses <= 2:
        hosts = list(network.hosts())
        first_usable = hosts[0] if hosts else None
        last_usable = hosts[-1] if hosts else None
    else:
        first_usable = network.network_address + 1
        last_usable = network.broadcast_address - 1

    if first_usable is not None and router == first_usable:
        return {"status": "VALUE", "value": "FIRST_USABLE"}
    if last_usable is not None and router == last_usable:
        return {"status": "VALUE", "value": "LAST_USABLE"}
    offset = int(router) - int(network.network_address)
    return {"status": "VALUE", "value": f"HOST_OFFSET_{offset}"}


def _specs(scope: str) -> list[ProfileInputSpec]:
    return [spec for spec in PROFILE_INPUT_SPECS if spec.scope == scope]


def _spec_by_input(scope: str) -> dict[str, ProfileInputSpec]:
    return {spec.input_key: spec for spec in _specs(scope)}


def _states_for_spec(spec: ProfileInputSpec, results: list[CollectionResult],
                     scalars: list[dict[str, Any]], options: list[dict[str, Any]]) -> tuple[
                         dict[tuple[str, str], dict[str, Any]], set[tuple[str, str]], str
                     ]:
    population_keys, _query_keys, basis = profile_population_for_spec(spec, results, scalars, options)
    rows = profile_parameter_rows(spec, scalars, options)
    effective_by_key = {
        object_key(result.grid, record): record
        for result in results
        for record in result.effective_records.get(spec.scope.lower(), [])
    }
    states = profile_object_states(spec, rows, population_keys, effective_by_key)
    if spec.input_key == "gateway_convention":
        raw_by_key = _raw_records_by_key(results, spec.scope.lower())
        states = {
            key: derive_gateway_convention(state, (raw_by_key.get(key) or {}).get("network"))
            for key, state in states.items()
        }
    return states, population_keys, basis


def build_profile_usefulness(results: list[CollectionResult], scalars: list[dict[str, Any]],
                             options: list[dict[str, Any]],
                             readiness: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Describe discriminative evidence without assigning a weighted score."""
    readiness_by_id = {str(row.get("Parameter ID")): row for row in readiness}
    output: list[dict[str, Any]] = []
    for spec in PROFILE_INPUT_SPECS:
        states, population_keys, basis = _states_for_spec(spec, results, scalars, options)
        counts = Counter(_state_label(state) for state in states.values())
        resolved_labels = {
            label for label in counts
            if label != "UNRESOLVED"
        }
        unresolved = counts["UNRESOLVED"]
        population = len(population_keys)
        resolved = population - unresolved
        configured_labels = {label for label in resolved_labels if label.startswith("VALUE:")}
        not_configured = counts["NOT_CONFIGURED"]
        dominant_label = ""
        dominant_count = 0
        if resolved_labels:
            dominant_label, dominant_count = sorted(
                ((label, counts[label]) for label in resolved_labels),
                key=lambda item: (-item[1], item[0]),
            )[0]
        if spec.semantic_role == "COMPOSITE_LATER":
            fingerprint_role = "DEFERRED"
        elif spec.input_key in CORE_INPUT_KEYS:
            fingerprint_role = "DERIVED_CORE" if spec.input_key == "gateway_convention" else "CORE"
        else:
            fingerprint_role = "OVERLAY"
        output.append({
            "Profile": spec.profile,
            "Input Key": spec.input_key,
            "Input": spec.label,
            "Parameter ID": spec.source_parameter_id,
            "Scope": spec.scope,
            "Semantic Role": spec.semantic_role,
            "Fingerprint Role": fingerprint_role,
            "Population Basis": basis,
            "Population Objects": population,
            "Resolved Objects": resolved,
            "Resolved %": round(resolved * 100.0 / population, 1) if population else None,
            "Unresolved Objects": unresolved,
            "Unresolved %": round(unresolved * 100.0 / population, 1) if population else None,
            "Distinct Resolved States": len(resolved_labels),
            "Distinct Configured Values": len(configured_labels),
            "Explicit Not Configured": not_configured,
            "Dominant State": dominant_label,
            "Dominant State Count": dominant_count,
            "Dominant % Population": round(dominant_count * 100.0 / population, 1) if population else None,
            "Dominant % Resolved": round(dominant_count * 100.0 / resolved, 1) if resolved else None,
            "Invariant Among Resolved": bool(resolved and len(resolved_labels) == 1),
            "Readiness": (readiness_by_id.get(spec.source_parameter_id) or {}).get("Readiness", "UNKNOWN"),
        })
    return output


def _canonical_state(state: dict[str, Any]) -> dict[str, Any]:
    status = str(state.get("status") or "UNRESOLVED")
    return {"status": status, "value": state.get("value") if status == "VALUE" else None}


def _fingerprint_id(scope: str, payload: dict[str, Any]) -> tuple[str, str]:
    encoded = _json(payload).encode("utf-8")
    digest = sha256(encoded).hexdigest()
    prefix = "NET" if scope == "Network" else "RNG"
    return f"{prefix}-FP{PROFILE_SCHEMA_VERSION}-{digest[:PROFILE_HASH_LENGTH]}", digest


def _object_display(record: dict[str, Any], scope: str) -> str:
    if scope == "Network":
        return str(record.get("network") or record.get("name") or "")
    start = record.get("start_addr")
    end = record.get("end_addr")
    if start and end:
        return f"{start}-{end}"
    return str(record.get("name") or record.get("_ref") or "")


def _association_family(record: dict[str, Any]) -> str:
    segment, _raw = range_association_segment(record)
    return segment


def _overlay_distribution(group_keys: set[tuple[str, str]], scope: str,
                          states_cache: dict[str, tuple[dict[tuple[str, str], dict[str, Any]],
                                                        set[tuple[str, str]], str]]) -> str:
    """Return a bounded descriptive overlay summary for one core profile."""
    data: dict[str, dict[str, Any]] = {}
    for spec in _specs(scope):
        if spec.input_key in CORE_INPUT_KEYS:
            continue
        states, population_keys, _basis = states_cache[spec.source_parameter_id]
        counts: Counter[str] = Counter()
        not_applicable = 0
        for key in group_keys:
            if key not in population_keys:
                not_applicable += 1
            else:
                counts[_state_label(states[key])] += 1
        top_states = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
        data[spec.input_key] = {
            "applicable": sum(counts.values()),
            "not_applicable": not_applicable,
            "distinct_states": len(counts),
            "top_states": top_states,
        }
    return _json(data)


def _profiles_for_threshold(counts: list[int], threshold: float) -> int | None:
    total = sum(counts)
    if not total:
        return None
    running = 0
    for index, count in enumerate(counts, start=1):
        running += count
        if running * 100.0 / total >= threshold:
            return index
    return len(counts)


def build_profile_fingerprints(results: list[CollectionResult], scalars: list[dict[str, Any]],
                               options: list[dict[str, Any]]) -> tuple[
                                   list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
                               ]:
    """Create exact deterministic core fingerprints and object assignments."""
    fingerprints: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    kpis: list[dict[str, Any]] = []

    for scope in ("Network", "Range"):
        profile_name = f"{scope} Profile v1"
        specs_by_input = _spec_by_input(scope)
        raw_by_key = _raw_records_by_key(results, scope.lower())
        states_cache = {
            spec.source_parameter_id: _states_for_spec(spec, results, scalars, options)
            for spec in _specs(scope)
        }

        if scope == "Network":
            applicable_keys = set(dhcp_profile_networks(results))
            not_applicable_keys: set[tuple[str, str]] = set()
            unresolved_association_keys: set[tuple[str, str]] = set()
            relevance = dhcp_profile_networks(results)
        else:
            applicable_keys = dhcp_associated_range_keys(results)
            all_keys = set(raw_by_key)
            not_applicable_keys = {
                key for key in all_keys
                if _association_family(raw_by_key[key]) == RANGE_SEGMENT_NONE
            }
            unresolved_association_keys = {
                key for key in all_keys
                if _association_family(raw_by_key[key]) in {RANGE_SEGMENT_OTHER, RANGE_SEGMENT_UNKNOWN}
            }
            relevance = {}

        core_states: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        for input_key in CORE_INPUT_KEYS:
            spec = specs_by_input[input_key]
            states, _population, _basis = states_cache[spec.source_parameter_id]
            core_states[input_key] = states

        payload_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        missing_by_key: dict[tuple[str, str], list[str]] = {}
        profile_id_by_key: dict[tuple[str, str], str] = {}
        full_hash_by_id: dict[str, str] = {}

        for key in sorted(applicable_keys):
            missing: list[str] = []
            fields: dict[str, dict[str, Any]] = {}
            for input_key in CORE_INPUT_KEYS:
                state = core_states[input_key].get(key, {"status": "UNRESOLVED", "value": None})
                if state.get("status") == "UNRESOLVED":
                    missing.append(specs_by_input[input_key].source_parameter_id)
                fields[input_key] = _canonical_state(state)
            if missing:
                missing_by_key[key] = missing
                continue
            payload: dict[str, Any] = {
                "schema_version": PROFILE_SCHEMA_VERSION,
                "profile_type": scope.lower(),
                "fields": fields,
            }
            if scope == "Range":
                family = _association_family(raw_by_key.get(key, {}))
                if family not in {RANGE_SEGMENT_MS_SERVER, RANGE_SEGMENT_MEMBER, RANGE_SEGMENT_FAILOVER}:
                    missing_by_key[key] = ["server_association_type"]
                    continue
                payload["association_family"] = family
            fingerprint_id, digest = _fingerprint_id(scope, payload)
            payload_by_key[key] = payload
            profile_id_by_key[key] = fingerprint_id
            full_hash_by_id[fingerprint_id] = digest

        groups: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for key, fingerprint_id in profile_id_by_key.items():
            groups[fingerprint_id].add(key)
        ordered_groups = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
        rank_by_id = {fingerprint_id: rank for rank, (fingerprint_id, _keys) in enumerate(ordered_groups, start=1)}
        profiled = len(profile_id_by_key)
        applicable = len(applicable_keys)

        for fingerprint_id, keys in ordered_groups:
            sample_key = sorted(keys)[0]
            payload = payload_by_key[sample_key]
            fields = payload["fields"]
            fingerprints.append({
                "Profile": profile_name,
                "Fingerprint ID": fingerprint_id,
                "Display Rank": rank_by_id[fingerprint_id],
                "Association Family": payload.get("association_family", ""),
                "Object Count": len(keys),
                "Share of Profiled %": round(len(keys) * 100.0 / profiled, 1) if profiled else None,
                "Share of Applicable %": round(len(keys) * 100.0 / applicable, 1) if applicable else None,
                "Lease Time": _display_state(fields["lease_time"]),
                "DNS Servers": _display_state(fields["dns_servers"]),
                "Domain Name": _display_state(fields["domain_name"]),
                "Gateway Convention": _display_state(fields["gateway_convention"]),
                "Canonical Payload": _json(payload),
                "Full SHA256": full_hash_by_id[fingerprint_id],
                "Feature Overlay Distributions": _overlay_distribution(keys, scope, states_cache),
            })

        for key in sorted(raw_by_key):
            record = raw_by_key[key]
            if scope == "Range" and key in not_applicable_keys:
                population_status = "NOT_APPLICABLE_TO_DHCP_PROFILE"
            elif scope == "Range" and key in unresolved_association_keys:
                population_status = "UNRESOLVED_ASSOCIATION"
            elif key not in applicable_keys:
                # Non-candidate Networks are intentionally absent from Network assignment rows.
                if scope == "Network":
                    continue
                population_status = "NOT_APPLICABLE_TO_DHCP_PROFILE"
            elif key in profile_id_by_key:
                population_status = "PROFILED"
            else:
                population_status = "UNRESOLVED_PROFILE_INPUTS"

            fingerprint_id = profile_id_by_key.get(key, "")
            assignments.append({
                "Profile": profile_name,
                "Grid": key[0],
                "Scope": scope,
                "Object Ref": record.get("_ref", key[1]),
                "Object": _object_display(record, scope),
                "Network View": record.get("network_view", ""),
                "Association Family": _association_family(record) if scope == "Range" else "",
                "Population Status": population_status,
                "Fingerprint ID": fingerprint_id,
                "Display Rank": rank_by_id.get(fingerprint_id, ""),
                "Missing Core Inputs": ", ".join(missing_by_key.get(key, [])),
                "Network Relevance Reasons": ", ".join(sorted(relevance.get(key, set()))) if scope == "Network" else "",
                "Lease Time": _display_state(core_states["lease_time"].get(key, {"status": "UNRESOLVED"})),
                "DNS Servers": _display_state(core_states["dns_servers"].get(key, {"status": "UNRESOLVED"})),
                "Domain Name": _display_state(core_states["domain_name"].get(key, {"status": "UNRESOLVED"})),
                "Gateway Convention": _display_state(core_states["gateway_convention"].get(key, {"status": "UNRESOLVED"})),
            })

        counts = [len(keys) for _fingerprint_id_value, keys in ordered_groups]
        unresolved = max(applicable - profiled, 0)
        kpis.append({
            "Profile": profile_name,
            "Applicable Objects": applicable,
            "Profiled Objects": profiled,
            "Profiled %": round(profiled * 100.0 / applicable, 1) if applicable else None,
            "Unresolved Profile Objects": unresolved,
            "Unresolved %": round(unresolved * 100.0 / applicable, 1) if applicable else None,
            "Distinct Profiles": len(counts),
            "Top-1 Share of Profiled %": round(counts[0] * 100.0 / profiled, 1) if counts and profiled else None,
            "Top-3 Share of Profiled %": round(sum(counts[:3]) * 100.0 / profiled, 1) if counts and profiled else None,
            "Profiles for 80%": _profiles_for_threshold(counts, 80.0),
            "Profiles for 90%": _profiles_for_threshold(counts, 90.0),
            "Profiles for 95%": _profiles_for_threshold(counts, 95.0),
            "Singleton Profiles": sum(count == 1 for count in counts),
        })

    return fingerprints, assignments, kpis


def build_profile_discovery(results: list[CollectionResult], scalars: list[dict[str, Any]],
                            options: list[dict[str, Any]],
                            readiness: list[dict[str, Any]]) -> tuple[
                                list[dict[str, Any]], list[dict[str, Any]],
                                list[dict[str, Any]], list[dict[str, Any]]
                            ]:
    usefulness = build_profile_usefulness(results, scalars, options, readiness)
    fingerprints, assignments, kpis = build_profile_fingerprints(results, scalars, options)
    return usefulness, fingerprints, assignments, kpis

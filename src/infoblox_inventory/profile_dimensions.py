"""Deterministic multi-dimensional profile fingerprints.

Dimensions are descriptive current-state evidence. They do not approve standards,
infer compliance, or reconstruct template provenance.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from typing import Any

from .models import CollectionResult
from .profile_discovery import _states_for_spec
from .profile_population import (
    NETWORK_POPULATION_BASIS,
    RANGE_DHCP_ASSOCIATED_BASIS,
    RANGE_POPULATION_BASIS,
    RANGE_SEGMENT_FAILOVER,
    RANGE_SEGMENT_MEMBER,
    RANGE_SEGMENT_MS_SERVER,
    RANGE_SEGMENT_NONE,
    RANGE_SEGMENT_OTHER,
    RANGE_SEGMENT_UNKNOWN,
    dhcp_associated_range_keys,
    dhcp_profile_networks,
    object_key,
    range_association_segment,
)
from .profile_readiness import PROFILE_INPUT_SPECS, ProfileInputSpec


DIMENSION_SCHEMA_VERSION = 1
DIMENSION_HASH_LENGTH = 12

DIMENSION_DEFINITIONS = (
    {
        "name": "DHCP Core",
        "key": "dhcp_core",
        "code": "CORE",
        "inputs": ("lease_time", "dns_servers", "domain_name", "gateway_convention"),
        "scopes": ("Network", "Range"),
    },
    {
        "name": "DNS/DDNS",
        "key": "dns_ddns",
        "code": "DNS",
        "inputs": (
            "domain_search", "ddns_enabled", "ddns_domain", "ddns_generate_hostname",
            "ddns_ttl", "ddns_update_fixed_addresses", "ddns_use_option81",
            "ddns_update_on_renewal",
        ),
        "scopes": ("Network", "Range"),
    },
    {
        "name": "PXE",
        "key": "pxe",
        "code": "PXE",
        "inputs": (
            "pxe_nextserver", "pxe_bootserver", "pxe_bootfile", "pxe_tftp_server_name",
            "pxe_bootfile_name_option", "pxe_lease_time", "pxe_lease_enabled",
        ),
        "scopes": ("Network", "Range"),
    },
    {
        "name": "Service",
        "key": "service",
        "code": "SVC",
        "inputs": ("ntp_servers", "deny_bootp"),
        "scopes": ("Network", "Range"),
    },
    {
        "name": "Association",
        "key": "association",
        "code": "ASSOC",
        "inputs": (),
        "scopes": ("Range",),
    },
)

PROFILE_DIMENSION_HEADERS = [
    "Profile", "Scope", "Dimension", "Population Basis", "Dimension Fingerprint ID",
    "Display Rank", "Object Count", "Share of Profiled %", "Share of Applicable %",
    "Identity Inputs", "Deferred Inputs", "Dimension Values", "Canonical Payload", "Full SHA256",
]

PROFILE_DIMENSION_ASSIGNMENT_HEADERS = [
    "Profile", "Grid", "Scope", "Object Ref", "Object", "Network View",
    "Association Family", "Dimension", "Population Status", "Dimension Fingerprint ID",
    "Display Rank", "Missing Inputs", "Deferred Inputs", "Dimension Values",
]

PROFILE_DIMENSION_KPI_HEADERS = [
    "Profile", "Scope", "Dimension", "Population Basis", "Applicable Objects",
    "Profiled Objects", "Profiled %", "Unresolved Dimension Objects", "Unresolved %",
    "Distinct Fingerprints", "Top-1 Share of Profiled %", "Singleton Fingerprints",
]

PROFILE_COMPOSITION_HEADERS = [
    "Profile", "Grid", "Scope", "Object Ref", "Object", "Network View",
    "Association Family", "DHCP Core", "DNS/DDNS", "PXE", "Service", "Association",
    "Composition Status",
]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _raw_records_by_key(
    results: list[CollectionResult], object_type: str
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        object_key(result.grid, record): record
        for result in results
        for record in result.records.get(object_type, [])
    }


def _object_display(record: dict[str, Any], scope: str) -> str:
    if scope == "Network":
        return str(record.get("network") or record.get("name") or record.get("_ref") or "")
    start = record.get("start_addr")
    end = record.get("end_addr")
    if start and end:
        return f"{start}-{end}"
    return str(record.get("name") or record.get("_ref") or "")


def _association_family(record: dict[str, Any]) -> str:
    segment, _raw = range_association_segment(record)
    return segment


def _canonical_state(state: dict[str, Any]) -> dict[str, Any]:
    status = str(state.get("status") or "UNRESOLVED")
    return {"status": status, "value": state.get("value") if status == "VALUE" else None}


def _display_state(state: dict[str, Any]) -> Any:
    status = str(state.get("status") or "UNRESOLVED")
    if status == "VALUE":
        value = state.get("value")
        if isinstance(value, str) and not value.strip():
            return "EMPTY_VALUE"
        return value
    return status


def _dimension_id(scope: str, code: str, payload: dict[str, Any]) -> tuple[str, str]:
    digest = sha256(_json(payload).encode("utf-8")).hexdigest()
    prefix = "NET" if scope == "Network" else "RNG"
    return f"{prefix}-{code}{DIMENSION_SCHEMA_VERSION}-{digest[:DIMENSION_HASH_LENGTH]}", digest


def _specs_for_dimension(scope: str, input_keys: tuple[str, ...]) -> list[ProfileInputSpec]:
    wanted = set(input_keys)
    return [
        spec for spec in PROFILE_INPUT_SPECS
        if spec.scope == scope and spec.input_key in wanted
    ]


def _dimension_population(scope: str, results: list[CollectionResult]) -> tuple[set[tuple[str, str]], str]:
    if scope == "Network":
        return set(dhcp_profile_networks(results)), NETWORK_POPULATION_BASIS
    return dhcp_associated_range_keys(results), RANGE_DHCP_ASSOCIATED_BASIS


def _dimension_values(fields: dict[str, dict[str, Any]]) -> str:
    return _json({name: _display_state(state) for name, state in fields.items()})


def _composition_rows(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in assignments:
        grouped[(str(row["Grid"]), str(row["Scope"]), str(row["Object Ref"]))].append(row)

    output: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        first = rows[0]
        scope = str(first["Scope"])
        by_dimension = {str(row["Dimension"]): row for row in rows}
        values: dict[str, Any] = {}
        for name in ("DHCP Core", "DNS/DDNS", "PXE", "Service", "Association"):
            row = by_dimension.get(name)
            if row is None:
                values[name] = ""
            else:
                values[name] = row.get("Dimension Fingerprint ID") or row.get("Population Status") or ""

        statuses = {name: str((by_dimension.get(name) or {}).get("Population Status") or "")
                    for name in by_dimension}
        if scope == "Range" and statuses.get("Association") == "UNRESOLVED_ASSOCIATION":
            composition_status = "UNRESOLVED_ASSOCIATION"
        elif scope == "Range" and str(first.get("Association Family") or "") == RANGE_SEGMENT_NONE:
            composition_status = "NOT_APPLICABLE_TO_DHCP_PROFILE"
        elif all(
            statuses.get(name) == "PROFILED"
            for name in (("DHCP Core", "DNS/DDNS", "PXE", "Service")
                         if scope == "Network"
                         else ("DHCP Core", "DNS/DDNS", "PXE", "Service", "Association"))
        ):
            composition_status = "COMPLETE"
        elif all(
            statuses.get(name) == "NOT_APPLICABLE_TO_DHCP_PROFILE"
            for name in ("DHCP Core", "DNS/DDNS", "PXE", "Service")
        ):
            composition_status = "NOT_APPLICABLE_TO_DHCP_PROFILE"
        else:
            composition_status = "PARTIAL"

        output.append({
            "Profile": first["Profile"],
            "Grid": key[0],
            "Scope": scope,
            "Object Ref": key[2],
            "Object": first["Object"],
            "Network View": first["Network View"],
            "Association Family": first.get("Association Family", ""),
            **values,
            "Composition Status": composition_status,
        })
    return output


def build_profile_dimensions(
    results: list[CollectionResult],
    scalars: list[dict[str, Any]],
    options: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Build exact fingerprints for independent profile dimensions.

    Different input applicability is represented explicitly as NOT_APPLICABLE.
    COMPOSITE_LATER inputs are reported as deferred and excluded from the hash.
    """
    fingerprints: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    kpis: list[dict[str, Any]] = []

    for scope in ("Network", "Range"):
        profile_name = f"{scope} Profile v1"
        raw_by_key = _raw_records_by_key(results, scope.lower())
        all_raw_keys = set(raw_by_key)
        base_population, population_basis = _dimension_population(scope, results)

        state_cache: dict[str, tuple[dict[tuple[str, str], dict[str, Any]], set[tuple[str, str]], str]] = {}
        for spec in (spec for spec in PROFILE_INPUT_SPECS if spec.scope == scope):
            state_cache[spec.source_parameter_id] = _states_for_spec(spec, results, scalars, options)

        for definition in DIMENSION_DEFINITIONS:
            if scope not in definition["scopes"]:
                continue

            name = str(definition["name"])
            code = str(definition["code"])
            dimension_key = str(definition["key"])
            if dimension_key == "association":
                applicable_keys = set(all_raw_keys)
                basis = RANGE_POPULATION_BASIS
                identity_specs: list[ProfileInputSpec] = []
                deferred_specs: list[ProfileInputSpec] = []
            else:
                applicable_keys = set(base_population)
                basis = population_basis
                specs = _specs_for_dimension(scope, tuple(definition["inputs"]))
                identity_specs = [spec for spec in specs if spec.semantic_role != "COMPOSITE_LATER"]
                deferred_specs = [spec for spec in specs if spec.semantic_role == "COMPOSITE_LATER"]

            payload_by_key: dict[tuple[str, str], dict[str, Any]] = {}
            fingerprint_by_key: dict[tuple[str, str], str] = {}
            missing_by_key: dict[tuple[str, str], list[str]] = {}
            full_hash_by_id: dict[str, str] = {}

            for key in sorted(applicable_keys):
                record = raw_by_key.get(key, {})
                fields: dict[str, dict[str, Any]] = {}
                missing: list[str] = []

                if dimension_key == "association":
                    family = _association_family(record)
                    if family in {
                        RANGE_SEGMENT_MS_SERVER, RANGE_SEGMENT_MEMBER,
                        RANGE_SEGMENT_FAILOVER, RANGE_SEGMENT_NONE,
                    }:
                        fields["association_family"] = {"status": "VALUE", "value": family}
                    else:
                        missing.append("server_association_type")
                        fields["association_family"] = {"status": "UNRESOLVED", "value": None}
                else:
                    for spec in identity_specs:
                        states, population_keys, _spec_basis = state_cache[spec.source_parameter_id]
                        if key not in population_keys:
                            state = {"status": "NOT_APPLICABLE", "value": None}
                        else:
                            state = states.get(key, {"status": "UNRESOLVED", "value": None})
                        state = _canonical_state(state)
                        fields[spec.input_key] = state
                        if state["status"] == "UNRESOLVED":
                            missing.append(spec.source_parameter_id)

                if missing:
                    missing_by_key[key] = missing
                    continue

                payload = {
                    "schema_version": DIMENSION_SCHEMA_VERSION,
                    "profile_type": scope.lower(),
                    "dimension": dimension_key,
                    "fields": fields,
                }
                fingerprint_id, digest = _dimension_id(scope, code, payload)
                payload_by_key[key] = payload
                fingerprint_by_key[key] = fingerprint_id
                full_hash_by_id[fingerprint_id] = digest

            groups: dict[str, set[tuple[str, str]]] = defaultdict(set)
            for key, fingerprint_id in fingerprint_by_key.items():
                groups[fingerprint_id].add(key)
            ordered_groups = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
            rank_by_id = {
                fingerprint_id: rank
                for rank, (fingerprint_id, _keys) in enumerate(ordered_groups, start=1)
            }
            profiled = len(fingerprint_by_key)
            applicable = len(applicable_keys)
            identity_ids = [spec.source_parameter_id for spec in identity_specs]
            deferred_ids = [spec.source_parameter_id for spec in deferred_specs]

            for fingerprint_id, keys in ordered_groups:
                sample_key = sorted(keys)[0]
                payload = payload_by_key[sample_key]
                fingerprints.append({
                    "Profile": profile_name,
                    "Scope": scope,
                    "Dimension": name,
                    "Population Basis": basis,
                    "Dimension Fingerprint ID": fingerprint_id,
                    "Display Rank": rank_by_id[fingerprint_id],
                    "Object Count": len(keys),
                    "Share of Profiled %": round(len(keys) * 100.0 / profiled, 1) if profiled else None,
                    "Share of Applicable %": round(len(keys) * 100.0 / applicable, 1) if applicable else None,
                    "Identity Inputs": ", ".join(identity_ids) if identity_ids else "server_association_type",
                    "Deferred Inputs": ", ".join(deferred_ids),
                    "Dimension Values": _dimension_values(payload["fields"]),
                    "Canonical Payload": _json(payload),
                    "Full SHA256": full_hash_by_id[fingerprint_id],
                })

            for key in sorted(all_raw_keys):
                record = raw_by_key[key]
                family = _association_family(record) if scope == "Range" else ""
                if dimension_key != "association" and key not in applicable_keys:
                    if scope == "Range" and family in {RANGE_SEGMENT_OTHER, RANGE_SEGMENT_UNKNOWN}:
                        status = "UNRESOLVED_ASSOCIATION"
                    else:
                        status = "NOT_APPLICABLE_TO_DHCP_PROFILE"
                elif key in fingerprint_by_key:
                    status = "PROFILED"
                elif dimension_key == "association" and family in {RANGE_SEGMENT_OTHER, RANGE_SEGMENT_UNKNOWN}:
                    status = "UNRESOLVED_ASSOCIATION"
                else:
                    status = "UNRESOLVED_DIMENSION_INPUTS"

                fingerprint_id = fingerprint_by_key.get(key, "")
                payload = payload_by_key.get(key)
                assignments.append({
                    "Profile": profile_name,
                    "Grid": key[0],
                    "Scope": scope,
                    "Object Ref": record.get("_ref", key[1]),
                    "Object": _object_display(record, scope),
                    "Network View": record.get("network_view", ""),
                    "Association Family": family,
                    "Dimension": name,
                    "Population Status": status,
                    "Dimension Fingerprint ID": fingerprint_id,
                    "Display Rank": rank_by_id.get(fingerprint_id, ""),
                    "Missing Inputs": ", ".join(missing_by_key.get(key, [])),
                    "Deferred Inputs": ", ".join(deferred_ids),
                    "Dimension Values": _dimension_values(payload["fields"]) if payload else "",
                })

            counts = [len(keys) for _fingerprint_id, keys in ordered_groups]
            unresolved = max(applicable - profiled, 0)
            kpis.append({
                "Profile": profile_name,
                "Scope": scope,
                "Dimension": name,
                "Population Basis": basis,
                "Applicable Objects": applicable,
                "Profiled Objects": profiled,
                "Profiled %": round(profiled * 100.0 / applicable, 1) if applicable else None,
                "Unresolved Dimension Objects": unresolved,
                "Unresolved %": round(unresolved * 100.0 / applicable, 1) if applicable else None,
                "Distinct Fingerprints": len(counts),
                "Top-1 Share of Profiled %": round(counts[0] * 100.0 / profiled, 1)
                if counts and profiled else None,
                "Singleton Fingerprints": sum(count == 1 for count in counts),
            })

    return fingerprints, assignments, kpis, _composition_rows(assignments)

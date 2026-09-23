"""Semantic abstraction for reusable DHCP templates.

Template models group stored Network/Range templates by functional shape while
keeping Grid-local values as parameters. This layer is descriptive evidence:
it neither approves a standard nor claims that an observed object was created
from a matching template.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, fields, is_dataclass
from hashlib import sha256
import json
import re
from typing import Any, Iterable

from .topology import DHCPOption, DHCPTemplateRecord, NetworkTemplateRecord, RangeTemplateRecord


MODEL_SCHEMA_VERSION = 1
MODEL_HASH_LENGTH = 12

ACTIVE = "ACTIVE_VALUE"
INACTIVE = "INACTIVE"
NOT_CONFIGURED = "NOT_CONFIGURED"
UNRESOLVED = "UNRESOLVED"
SHAPE_DISABLED = "DISABLED"

POLICY_LITERAL = "POLICY_LITERAL"
GRID_LOCAL = "GRID_LOCAL"
TOPOLOGY_DERIVED = "TOPOLOGY_DERIVED"
STRUCTURE_LITERAL = "STRUCTURE_LITERAL"
REFERENCE_LOCAL = "REFERENCE_LOCAL"

ABSTRACT_ROLES = {GRID_LOCAL, TOPOLOGY_DERIVED, REFERENCE_LOCAL}

TEMPLATE_MODEL_HEADERS = [
    "Model ID", "Template Type", "Template Count", "Grid Count", "Grid Coverage %",
    "Grids", "Template Names", "Dimensions", "Shape Parameters",
    "Canonical Shape", "Full SHA256",
]

TEMPLATE_ASSIGNMENT_HEADERS = [
    "Grid", "Template Type", "Template Name", "Template Ref", "Model ID",
    "Normalization Status", "Active Parameters", "Inactive Parameters",
    "Not Configured Parameters", "Unresolved Parameters", "Local Parameters",
    "Dimensions",
]

TEMPLATE_SEMANTIC_HEADERS = [
    "Grid", "Template Type", "Template Name", "Template Ref", "Model ID",
    "Dimension", "Parameter", "Source", "Parameterization Role", "Activity State",
    "Stored Value", "Use Flag", "Shape Value", "Included In Shape",
]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    dimension: str
    field: str
    role: str
    use_flag: str | None = None
    list_like: bool = False


@dataclass(frozen=True)
class OptionSpec:
    key: str
    dimension: str
    code: int
    role: str
    list_like: bool = False


COMMON_FIELDS = (
    FieldSpec("pxe.bootfile", "PXE", "bootfile", GRID_LOCAL, "use_bootfile"),
    FieldSpec("pxe.bootserver", "PXE", "bootserver", GRID_LOCAL, "use_bootserver"),
    FieldSpec("pxe.nextserver", "PXE", "nextserver", GRID_LOCAL, "use_nextserver"),
    FieldSpec("service.deny_bootp", "Service", "deny_bootp", POLICY_LITERAL, "use_deny_bootp"),
    FieldSpec("pxe.lease_enabled", "PXE", "enable_pxe_lease_time", POLICY_LITERAL, "use_pxe_lease_time"),
    FieldSpec("pxe.lease_time", "PXE", "pxe_lease_time", POLICY_LITERAL, "use_pxe_lease_time"),
    FieldSpec(
        "service.ignore_option_list_request", "Service", "ignore_dhcp_option_list_request",
        POLICY_LITERAL, "use_ignore_dhcp_option_list_request",
    ),
)

NETWORK_FIELDS = COMMON_FIELDS + (
    FieldSpec("ddns.enabled", "DNS/DDNS", "enable_ddns", POLICY_LITERAL, "use_enable_ddns"),
    FieldSpec("ddns.domain", "DNS/DDNS", "ddns_domainname", GRID_LOCAL, "use_ddns_domainname"),
    FieldSpec(
        "ddns.generate_hostname", "DNS/DDNS", "ddns_generate_hostname",
        POLICY_LITERAL, "use_ddns_generate_hostname",
    ),
    FieldSpec("ddns.ttl", "DNS/DDNS", "ddns_ttl", POLICY_LITERAL, "use_ddns_ttl"),
    FieldSpec(
        "ddns.update_fixed_addresses", "DNS/DDNS", "ddns_update_fixed_addresses",
        POLICY_LITERAL, "use_ddns_update_fixed_addresses",
    ),
    FieldSpec(
        "ddns.use_option81", "DNS/DDNS", "ddns_use_option81",
        POLICY_LITERAL, "use_ddns_use_option81",
    ),
    FieldSpec(
        "ddns.update_on_renewal", "DNS/DDNS", "update_dns_on_lease_renewal",
        POLICY_LITERAL, "use_update_dns_on_lease_renewal",
    ),
    FieldSpec("structure.netmask", "Template Structure", "netmask", TOPOLOGY_DERIVED),
    FieldSpec(
        "structure.allow_any_netmask", "Template Structure", "allow_any_netmask",
        STRUCTURE_LITERAL,
    ),
    FieldSpec("structure.members", "Template Structure", "members", REFERENCE_LOCAL),
    FieldSpec(
        "structure.delegated_member", "Template Structure", "delegated_member", REFERENCE_LOCAL,
    ),
    FieldSpec(
        "structure.range_templates", "Template Structure", "range_templates", REFERENCE_LOCAL,
    ),
    FieldSpec(
        "structure.fixed_address_templates", "Template Structure",
        "fixed_address_templates", REFERENCE_LOCAL,
    ),
    FieldSpec("service.authority", "Service", "authority", POLICY_LITERAL, "use_authority"),
    FieldSpec(
        "lease.scavenge_time", "Lease Lifecycle", "lease_scavenge_time",
        POLICY_LITERAL, "use_lease_scavenge_time",
    ),
    FieldSpec(
        "lease.recycle", "Lease Lifecycle", "recycle_leases",
        POLICY_LITERAL, "use_recycle_leases",
    ),
)

RANGE_FIELDS = COMMON_FIELDS + (
    FieldSpec("ddns.enabled", "DNS/DDNS", "enable_ddns", POLICY_LITERAL, "use_enable_ddns"),
    FieldSpec("ddns.domain", "DNS/DDNS", "ddns_domainname", GRID_LOCAL, "use_ddns_domainname"),
    FieldSpec(
        "ddns.generate_hostname", "DNS/DDNS", "ddns_generate_hostname",
        POLICY_LITERAL, "use_ddns_generate_hostname",
    ),
    FieldSpec(
        "ddns.update_on_renewal", "DNS/DDNS", "update_dns_on_lease_renewal",
        POLICY_LITERAL, "use_update_dns_on_lease_renewal",
    ),
    FieldSpec("structure.offset", "Template Structure", "offset", TOPOLOGY_DERIVED),
    FieldSpec(
        "structure.number_of_addresses", "Template Structure",
        "number_of_addresses", TOPOLOGY_DERIVED,
    ),
    FieldSpec(
        "association.family", "Association", "server_association_type", STRUCTURE_LITERAL,
    ),
    FieldSpec("association.member", "Association", "member", REFERENCE_LOCAL),
    FieldSpec("association.ms_server", "Association", "ms_server", REFERENCE_LOCAL),
    FieldSpec(
        "association.delegated_member", "Association", "delegated_member", REFERENCE_LOCAL,
    ),
    FieldSpec(
        "association.failover", "Association", "failover_association", REFERENCE_LOCAL,
    ),
    FieldSpec("structure.exclusions", "Template Structure", "exclude", TOPOLOGY_DERIVED),
    FieldSpec(
        "lease.scavenge_time", "Lease Lifecycle", "lease_scavenge_time",
        POLICY_LITERAL, "use_lease_scavenge_time",
    ),
    FieldSpec(
        "lease.recycle", "Lease Lifecycle", "recycle_leases",
        POLICY_LITERAL, "use_recycle_leases",
    ),
)

KNOWN_OPTIONS = (
    OptionSpec("dhcp.lease_time", "DHCP Core", 51, POLICY_LITERAL),
    OptionSpec("dhcp.dns_servers", "DHCP Core", 6, GRID_LOCAL, list_like=True),
    OptionSpec("dhcp.domain_name", "DHCP Core", 15, GRID_LOCAL),
    OptionSpec("dhcp.gateway", "DHCP Core", 3, TOPOLOGY_DERIVED, list_like=True),
    OptionSpec("dhcp.domain_search", "DNS/DDNS", 119, GRID_LOCAL, list_like=True),
    OptionSpec("dhcp.ntp_servers", "Service", 42, GRID_LOCAL, list_like=True),
    OptionSpec("pxe.tftp_server_name", "PXE", 66, GRID_LOCAL),
    OptionSpec("pxe.bootfile_name", "PXE", 67, GRID_LOCAL),
)

_OPTION_BY_CODE = {spec.code: spec for spec in KNOWN_OPTIONS}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: _plain(getattr(value, field.name))
            for field in fields(value)
            if field.name not in {"raw", "extra_fields", "comment"}
        }
    if isinstance(value, dict):
        return {
            str(key): _plain(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key not in {"raw", "extra_fields", "comment"}
        }
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _value_kind(value: Any) -> str:
    if value is None:
        return "NONE"
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, list):
        return "LIST"
    if isinstance(value, dict) or is_dataclass(value):
        return "OBJECT"
    return "STRING"


def _split_list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"\s*,\s*", text) if part.strip()]


def _cardinality(value: Any, list_like: bool) -> int:
    if list_like:
        return len(_split_list_value(value))
    if isinstance(value, list):
        return len(value)
    return 0 if value is None else 1


def _reference_types(value: Any) -> list[str]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if is_dataclass(item):
            extra = getattr(item, "extra_fields", None)
            raw = getattr(item, "raw", None)
            if isinstance(extra, dict) and extra.get("_struct"):
                found.add(str(extra["_struct"]))
            elif isinstance(raw, dict) and raw.get("_struct"):
                found.add(str(raw["_struct"]))
            return
        if isinstance(item, dict):
            if item.get("_struct"):
                found.add(str(item["_struct"]))
            extra = item.get("extra_fields")
            if isinstance(extra, dict) and extra.get("_struct"):
                found.add(str(extra["_struct"]))
            return
        if isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return sorted(found)


def _shape_value(role: str, state: str, value: Any, *, list_like: bool = False) -> Any:
    if state != ACTIVE:
        return None
    if role in ABSTRACT_ROLES:
        result = {
            "placeholder": role,
            "kind": _value_kind(value),
            "cardinality": _cardinality(value, list_like),
        }
        if role == REFERENCE_LOCAL:
            reference_types = _reference_types(value)
            if reference_types:
                result["reference_types"] = reference_types
        return result
    return _plain(value)


def _stored_value(value: Any) -> Any:
    return _plain(value)


def _field_state(record: DHCPTemplateRecord, spec: FieldSpec) -> tuple[str, Any, Any]:
    raw = record.raw or {}
    value = getattr(record, spec.field, None)
    if spec.use_flag:
        use_present = spec.use_flag in raw
        use_value = getattr(record, spec.use_flag, None)
        if use_present and use_value is False:
            return INACTIVE, value, use_value
        if use_present and use_value is True:
            if spec.field not in raw or value is None:
                return UNRESOLVED, value, use_value
            return ACTIVE, value, use_value
        if spec.field not in raw and not use_present:
            return NOT_CONFIGURED, value, use_value
        return UNRESOLVED, value, use_value
    if spec.field not in raw:
        return NOT_CONFIGURED, value, None
    if value is None:
        return NOT_CONFIGURED, value, None
    return ACTIVE, value, None


def _option_values(options: Iterable[DHCPOption]) -> list[Any]:
    return [option.value for option in options]


def _option_state(
    record: DHCPTemplateRecord, options: list[DHCPOption]
) -> tuple[str, Any, Any]:
    if not options:
        return NOT_CONFIGURED, None, None
    stored = _option_values(options)
    if record.use_options is False:
        return INACTIVE, stored[0] if len(stored) == 1 else stored, record.use_options
    flags = [option.use_option for option in options]
    if all(flag is False for flag in flags):
        return INACTIVE, stored[0] if len(stored) == 1 else stored, record.use_options
    if record.use_options is True and all(flag is True for flag in flags):
        active_values = [option.value for option in options]
        return ACTIVE, active_values[0] if len(active_values) == 1 else active_values, record.use_options
    return UNRESOLVED, stored[0] if len(stored) == 1 else stored, record.use_options


def _semantic_row(
    record: DHCPTemplateRecord,
    *,
    dimension: str,
    key: str,
    source: str,
    role: str,
    state: str,
    value: Any,
    use_flag: Any,
    list_like: bool = False,
) -> dict[str, Any]:
    return {
        "Grid": record.grid,
        "Template Type": record.object_type,
        "Template Name": record.name or "",
        "Template Ref": record.object_ref or "",
        "Model ID": "",
        "Dimension": dimension,
        "Parameter": key,
        "Source": source,
        "Parameterization Role": role,
        "Activity State": state,
        "Stored Value": _stored_value(value),
        "Use Flag": use_flag,
        "Shape Value": _shape_value(role, state, value, list_like=list_like),
        "Included In Shape": True,
    }


def _record_specs(record: DHCPTemplateRecord) -> tuple[FieldSpec, ...]:
    if isinstance(record, NetworkTemplateRecord):
        return NETWORK_FIELDS
    if isinstance(record, RangeTemplateRecord):
        return RANGE_FIELDS
    return ()


def _unknown_option_specs(record: DHCPTemplateRecord) -> list[tuple[str, str, list[DHCPOption]]]:
    groups: dict[tuple[str, int], list[DHCPOption]] = defaultdict(list)
    for option in record.options or []:
        vendor = str(option.vendor_class or "DHCP")
        if option.num in _OPTION_BY_CODE and vendor.upper() == "DHCP":
            continue
        code = int(option.num) if isinstance(option.num, int) else -1
        groups[(vendor, code)].append(option)
    return [
        (f"option.{vendor}.{code}", "Other DHCP Options", options)
        for (vendor, code), options in sorted(groups.items())
    ]


def template_semantic_rows(
    records: list[Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, (NetworkTemplateRecord, RangeTemplateRecord)):
            continue

        for spec in _record_specs(record):
            state, value, use_flag = _field_state(record, spec)
            rows.append(_semantic_row(
                record,
                dimension=spec.dimension,
                key=spec.key,
                source=f"field:{spec.field}",
                role=spec.role,
                state=state,
                value=value,
                use_flag=use_flag,
                list_like=spec.list_like,
            ))

        by_code: dict[int, list[DHCPOption]] = defaultdict(list)
        for option in record.options or []:
            if isinstance(option.num, int) and str(option.vendor_class or "DHCP").upper() == "DHCP":
                by_code[option.num].append(option)
        for spec in KNOWN_OPTIONS:
            state, value, use_flag = _option_state(record, by_code.get(spec.code, []))
            rows.append(_semantic_row(
                record,
                dimension=spec.dimension,
                key=spec.key,
                source=f"option:{spec.code}",
                role=spec.role,
                state=state,
                value=value,
                use_flag=use_flag,
                list_like=spec.list_like,
            ))

        for key, dimension, options in _unknown_option_specs(record):
            state, value, use_flag = _option_state(record, options)
            row = _semantic_row(
                record,
                dimension=dimension,
                key=key,
                source=f"option:{options[0].num if options else ''}",
                role=POLICY_LITERAL,
                state=state,
                value=value,
                use_flag=use_flag,
            )
            # Unknown disabled stored options remain evidence but do not define a
            # reusable shape. Active/ambiguous unknown options remain conservative.
            if state == INACTIVE:
                row["Included In Shape"] = False
            rows.append(row)
    return rows


def _shape_state(activity_state: str) -> str:
    """Collapse inactive stored evidence and absence into one reusable-shape state."""
    if activity_state in {INACTIVE, NOT_CONFIGURED}:
        return SHAPE_DISABLED
    return activity_state


def _model_id(template_type: str, payload: dict[str, Any]) -> tuple[str, str]:
    digest = sha256(_json(payload).encode("utf-8")).hexdigest()
    prefix = "NTPL" if template_type == "networktemplate" else "RTPL"
    return f"{prefix}-SH{MODEL_SCHEMA_VERSION}-{digest[:MODEL_HASH_LENGTH]}", digest


def _shape_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    template_type = str(rows[0]["Template Type"])
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "template_type": template_type,
        "parameters": {
            str(row["Parameter"]): {
                "dimension": row["Dimension"],
                "role": row["Parameterization Role"],
                "state": _shape_state(str(row["Activity State"])),
                "shape_value": row["Shape Value"],
            }
            for row in sorted(rows, key=lambda item: str(item["Parameter"]))
            if row.get("Included In Shape") is True
        },
    }


def _matrix_display(parameter: str, value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if parameter == "structure.netmask":
        return f"/{value}"
    if parameter in {"structure.range_templates", "structure.fixed_address_templates"}:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
    if parameter == "structure.members" and isinstance(value, list):
        items: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                items.append(str(item))
                continue
            name = item.get("name")
            address = item.get("ipv4addr")
            if name and address:
                items.append(f"{name} ({address})")
            elif name or address:
                items.append(str(name or address))
            else:
                items.append(_json(item))
        return ", ".join(items)
    if parameter.startswith("association.") and isinstance(value, dict):
        return str(value.get("name") or value.get("ipv4addr") or _json(value))
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def build_template_semantic_model(
    records: list[Any], grids: list[str]
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
]:
    semantics = template_semantic_rows(records)
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in semantics:
        grouped[(
            str(row["Grid"]), str(row["Template Type"]),
            str(row["Template Ref"]), str(row["Template Name"]),
        )].append(row)

    assignments: list[dict[str, Any]] = []
    model_groups: dict[str, list[tuple[tuple[str, str, str, str], list[dict[str, Any]], dict[str, Any], str]]] = defaultdict(list)
    for key, rows in sorted(grouped.items()):
        payload = _shape_payload(rows)
        model_id, digest = _model_id(key[1], payload)
        for row in rows:
            row["Model ID"] = model_id
        model_groups[model_id].append((key, rows, payload, digest))
        state_counts = defaultdict(int)
        for row in rows:
            state_counts[str(row["Activity State"])] += 1
        assignments.append({
            "Grid": key[0],
            "Template Type": key[1],
            "Template Name": key[3],
            "Template Ref": key[2],
            "Model ID": model_id,
            "Normalization Status": next(
                (
                    str(record.status)
                    for record in records
                    if isinstance(record, DHCPTemplateRecord)
                    and record.grid == key[0]
                    and record.object_type == key[1]
                    and str(record.object_ref or "") == key[2]
                    and str(record.name or "") == key[3]
                ),
                "",
            ),
            "Active Parameters": state_counts[ACTIVE],
            "Inactive Parameters": state_counts[INACTIVE],
            "Not Configured Parameters": state_counts[NOT_CONFIGURED],
            "Unresolved Parameters": state_counts[UNRESOLVED],
            "Local Parameters": sum(
                row["Parameterization Role"] in ABSTRACT_ROLES for row in rows
            ),
            "Dimensions": ", ".join(sorted({str(row["Dimension"]) for row in rows})),
        })

    total_grids = len(set(grids))
    models: list[dict[str, Any]] = []
    for model_id, group in sorted(model_groups.items()):
        keys = [item[0] for item in group]
        payload = group[0][2]
        digest = group[0][3]
        model_grids = sorted({key[0] for key in keys})
        names = sorted({key[3] for key in keys if key[3]})
        dimensions = sorted({
            str(row["Dimension"]) for _key, rows, _payload, _digest in group for row in rows
        })
        models.append({
            "Model ID": model_id,
            "Template Type": keys[0][1],
            "Template Count": len(keys),
            "Grid Count": len(model_grids),
            "Grid Coverage %": (
                round(len(model_grids) * 100.0 / total_grids, 1) if total_grids else None
            ),
            "Grids": ", ".join(model_grids),
            "Template Names": ", ".join(names),
            "Dimensions": ", ".join(dimensions),
            "Shape Parameters": len(payload["parameters"]),
            "Canonical Shape": _json(payload),
            "Full SHA256": digest,
        })

    grid_headers = [
        "Model ID", "Template Type", "Dimension", "Parameter", "Parameterization Role",
        "Activity State", *list(dict.fromkeys(grids)),
    ]
    local_rows: list[dict[str, Any]] = []
    local_index: dict[tuple[str, str, str, str, str, str], dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in semantics:
        if row["Parameterization Role"] not in ABSTRACT_ROLES:
            continue
        # Human-facing Grid matrix should contain actual local values, not one
        # row per absent parameter. Full absence/state evidence remains in the
        # hidden Template_Semantics sheet.
        if row["Activity State"] == NOT_CONFIGURED:
            continue
        stored_value = row.get("Stored Value")
        if stored_value in (None, "", [], {}):
            continue
        index_key = (
            str(row["Model ID"]), str(row["Template Type"]), str(row["Dimension"]),
            str(row["Parameter"]), str(row["Parameterization Role"]),
            str(row["Activity State"]),
        )
        display = _matrix_display(str(row["Parameter"]), row["Stored Value"])
        name = str(row["Template Name"] or row["Template Ref"])
        local_index[index_key][str(row["Grid"])].append(f"{name}={display}")

    for key, per_grid in sorted(local_index.items()):
        local_rows.append({
            "Model ID": key[0],
            "Template Type": key[1],
            "Dimension": key[2],
            "Parameter": key[3],
            "Parameterization Role": key[4],
            "Activity State": key[5],
            **{
                grid: " | ".join(sorted(set(per_grid.get(grid, []))))
                for grid in grids
            },
        })

    return models, assignments, local_rows, semantics, grid_headers

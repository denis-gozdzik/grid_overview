"""Human-facing NetworkTemplate -> RangeTemplate provisioning bundles."""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from typing import Any

from .topology import DHCPTemplateRecord, MemberAssociation, NetworkTemplateRecord, RangeTemplateRecord


BUNDLE_SCHEMA_VERSION = 1
BUNDLE_HASH_LENGTH = 12

TEMPLATE_BUNDLE_HEADERS = [
    "Grid", "Bundle Model ID", "Bundle Status", "Provisioning Family",
    "Network Template", "Network Model ID", "Network Prefix", "Network Member Family",
    "Range Template", "Range Model ID", "Range Association",
    "Range Start", "Range Addresses", "Range End", "Geometry Signature", "Exclusion Pattern",
    "Fixed Address Templates", "Options State", "Stored Enabled Options",
    "Review Flags", "Notes",
]

TEMPLATE_BUNDLE_MODEL_HEADERS = [
    "Bundle Model ID", "Provisioning Family", "Bundle Count", "Grid Count", "Grid Coverage %",
    "Grids", "Network Models", "Range Models", "Geometry Signature",
    "Network Templates", "Range Templates", "Review Flags", "Canonical Shape", "Full SHA256",
]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _record_key(record: DHCPTemplateRecord) -> tuple[str, str, str, str]:
    return (
        str(record.grid),
        str(record.object_type),
        str(record.object_ref or ""),
        str(record.name or ""),
    )


def _assignment_index(assignments: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], str]:
    return {
        (
            str(row.get("Grid") or ""),
            str(row.get("Template Type") or ""),
            str(row.get("Template Ref") or ""),
            str(row.get("Template Name") or ""),
        ): str(row.get("Model ID") or "")
        for row in assignments
    }


def _struct_type(value: Any) -> str:
    extra = getattr(value, "extra_fields", None)
    raw = getattr(value, "raw", None)
    if isinstance(extra, dict) and extra.get("_struct"):
        return str(extra["_struct"])
    if isinstance(raw, dict) and raw.get("_struct"):
        return str(raw["_struct"])
    return ""


def _member_family(values: list[MemberAssociation] | None) -> str:
    types = {_struct_type(value) for value in (values or [])}
    types.discard("")
    mapped = {
        "dhcpmember": "INFOBLOX_MEMBER",
        "msdhcpserver": "MS_SERVER",
    }
    families = sorted({mapped.get(value, value.upper()) for value in types})
    if not families and values:
        return "UNKNOWN_MEMBER"
    return ", ".join(families)


def _range_reference_family(record: RangeTemplateRecord) -> str:
    if record.server_association_type:
        return str(record.server_association_type)
    if record.member is not None:
        return "MEMBER"
    if record.ms_server is not None:
        return "MS_SERVER"
    if record.failover_association:
        return "FAILOVER"
    return "NONE"


def _provisioning_family(network: NetworkTemplateRecord | None, range_record: RangeTemplateRecord | None) -> str:
    network_family = _member_family(network.members) if network is not None else ""
    range_family = _range_reference_family(range_record) if range_record is not None else ""
    if network_family == "MS_SERVER" and range_family == "MS_SERVER":
        return "MS_SERVER"
    if network_family == "INFOBLOX_MEMBER" and range_family in {"MEMBER", "FAILOVER"}:
        return "INFOBLOX"
    if network is None:
        return f"ORPHAN_{range_family or 'UNKNOWN'}"
    if range_record is None:
        return network_family or "NETWORK_ONLY"
    return "MIXED_OR_INCONSISTENT"


def _total_addresses(network: NetworkTemplateRecord | None) -> int | None:
    if network is None or not isinstance(network.netmask, int) or not 0 <= network.netmask <= 32:
        return None
    return 1 << (32 - network.netmask)


def _range_geometry_signature(
    network: NetworkTemplateRecord | None,
    range_record: RangeTemplateRecord | None,
) -> dict[str, Any] | None:
    """Normalize Range geometry relative to the parent prefix when available.

    This intentionally lets /24 and /27 templates share one geometry model when
    they use the same start offset, end margin and end-anchored exclusions.
    """
    if range_record is None:
        return None
    offset = range_record.offset
    count = range_record.number_of_addresses
    total = _total_addresses(network)

    if not isinstance(offset, int) or not isinstance(count, int):
        return {
            "status": "UNRESOLVED",
            "offset": offset,
            "number_of_addresses": count,
        }

    end_offset = offset + count - 1
    if total is None:
        end_shape: Any = {"host_offset": end_offset}
    else:
        end_margin = (total - 1) - end_offset
        end_shape = "LAST_USABLE" if end_margin == 1 else {"broadcast_margin": end_margin}

    exclusions = []
    for exclusion in range_record.exclude or []:
        ex_offset = exclusion.offset
        ex_count = exclusion.number_of_addresses
        if not isinstance(ex_offset, int) or not isinstance(ex_count, int):
            exclusions.append({"status": "UNRESOLVED"})
            continue
        if total is None:
            exclusions.append({"anchor": "START", "offset": ex_offset, "length": ex_count})
            continue
        ex_end = ex_offset + ex_count - 1
        end_margin = (total - 1) - ex_end
        # Use the nearest stable edge as anchor. This makes identical reserved
        # tail blocks comparable across different prefix lengths.
        if end_margin < ex_offset:
            exclusions.append({"anchor": "END", "margin": end_margin, "length": ex_count})
        else:
            exclusions.append({"anchor": "START", "offset": ex_offset, "length": ex_count})

    exclusions = sorted(exclusions, key=_json)
    return {
        "start": "FIRST_USABLE" if offset == 1 else {"host_offset": offset},
        "end": end_shape,
        "exclusions": exclusions,
    }


def _range_geometry(
    network: NetworkTemplateRecord | None,
    range_record: RangeTemplateRecord | None,
) -> tuple[str, str, str, str, str]:
    if range_record is None:
        return "", "", "", "", ""
    offset = range_record.offset
    count = range_record.number_of_addresses
    start = "" if offset is None else ("FIRST_USABLE" if offset == 1 else f"HOST_OFFSET_{offset}")
    addresses = "" if count is None else str(count)
    end = ""
    exclusions = []

    total = _total_addresses(network)
    if isinstance(offset, int) and isinstance(count, int):
        end_offset = offset + count - 1
        if total is not None:
            if end_offset == total - 2:
                end = "LAST_USABLE"
            elif end_offset == total - 1:
                end = "BROADCAST_OFFSET"
            else:
                end = f"HOST_OFFSET_{end_offset} ({total - 1 - end_offset} before broadcast)"
        else:
            end = f"HOST_OFFSET_{end_offset}"

    for exclusion in range_record.exclude or []:
        ex_offset = exclusion.offset
        ex_count = exclusion.number_of_addresses
        if ex_offset is None or ex_count is None:
            exclusions.append("UNRESOLVED")
            continue
        if total is not None:
            ex_end = ex_offset + ex_count - 1
            exclusions.append(
                f"offset {ex_offset}, count {ex_count}, end {total - 1 - ex_end} before broadcast"
            )
        else:
            exclusions.append(f"offset {ex_offset}, count {ex_count}")

    signature = _range_geometry_signature(network, range_record)
    return (
        start,
        addresses,
        end,
        _json(signature) if signature is not None else "",
        "; ".join(exclusions) if exclusions else "NONE",
    )


def _options_summary(record: DHCPTemplateRecord | None) -> tuple[str, str, list[str]]:
    if record is None:
        return "", "", []
    enabled = [
        option for option in (record.options or [])
        if option.use_option is True and option.value not in (None, "")
    ]
    option_labels = [str(option.name or option.num or "?") for option in enabled]
    flags: list[str] = []
    if record.use_options is False and enabled:
        flags.append("STORED_OPTIONS_DISABLED_BY_CONTAINER")
        state = "DISABLED (use_options=False)"
    elif record.use_options is True:
        state = "ENABLED"
    elif record.use_options is False:
        state = "DISABLED"
    else:
        state = "UNKNOWN"
    return state, ", ".join(option_labels), flags


def _bundle_flags(
    network: NetworkTemplateRecord | None,
    range_record: RangeTemplateRecord | None,
    option_flags: list[str],
) -> list[str]:
    flags = list(option_flags)
    if network is not None and range_record is not None:
        if _provisioning_family(network, range_record) == "MIXED_OR_INCONSISTENT":
            flags.append("NETWORK_RANGE_ASSOCIATION_MISMATCH")
    if range_record is not None:
        if range_record.server_association_type == "NONE" and (
            range_record.member is not None
            or range_record.ms_server is not None
            or range_record.failover_association
        ):
            flags.append("ASSOCIATION_NONE_WITH_SERVER_REFERENCE")
    return sorted(set(flags))


def _bundle_shape(
    network_model: str,
    range_model: str,
    provisioning_family: str,
    geometry: dict[str, Any] | None,
    fixed_count: int,
    status: str,
) -> dict[str, Any]:
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "status": status,
        "provisioning_family": provisioning_family,
        "network_model": network_model or None,
        "range_model": range_model or None,
        "range_geometry": geometry,
        "fixed_address_template_count": fixed_count,
    }


def _bundle_model_id(payload: dict[str, Any]) -> tuple[str, str]:
    digest = sha256(_json(payload).encode("utf-8")).hexdigest()
    return f"BNDL-SH{BUNDLE_SCHEMA_VERSION}-{digest[:BUNDLE_HASH_LENGTH]}", digest


def build_template_bundles(
    records: list[Any],
    assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return one row per linked NetworkTemplate/RangeTemplate pair plus orphans."""
    model_by_key = _assignment_index(assignments)
    networks = [record for record in records if isinstance(record, NetworkTemplateRecord)]
    ranges = [record for record in records if isinstance(record, RangeTemplateRecord)]
    ranges_by_grid_name = {(record.grid, str(record.name or "")): record for record in ranges}
    linked_range_keys: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []

    def emit(
        network: NetworkTemplateRecord | None,
        range_record: RangeTemplateRecord | None,
        *,
        status: str,
        requested_range_name: str = "",
    ) -> None:
        option_record = range_record or network
        option_state, enabled_options, option_flags = _options_summary(option_record)
        flags = _bundle_flags(network, range_record, option_flags)
        start, addresses, end, geometry_text, exclusions = _range_geometry(network, range_record)
        network_model = model_by_key.get(_record_key(network), "") if network else ""
        range_model = model_by_key.get(_record_key(range_record), "") if range_record else ""
        fixed_list = list(network.fixed_address_templates or []) if network else []
        fixed_templates = ", ".join(fixed_list)
        family = _provisioning_family(network, range_record)
        geometry = _range_geometry_signature(network, range_record)
        payload = _bundle_shape(
            network_model, range_model, family, geometry, len(fixed_list), status
        )
        bundle_id, digest = _bundle_model_id(payload)
        notes: list[str] = []
        if status == "MISSING_RANGE_TEMPLATE":
            notes.append(f"Linked RangeTemplate not collected/found: {requested_range_name}")
        if status == "ORPHAN_RANGE_TEMPLATE":
            notes.append("RangeTemplate is not referenced by any collected NetworkTemplate.")
        rows.append({
            "Grid": network.grid if network else range_record.grid if range_record else "",
            "Bundle Model ID": bundle_id,
            "Bundle Status": status,
            "Provisioning Family": family,
            "Network Template": network.name or "" if network else "",
            "Network Model ID": network_model,
            "Network Prefix": f"/{network.netmask}" if network and network.netmask is not None else "",
            "Network Member Family": _member_family(network.members) if network else "",
            "Range Template": range_record.name or "" if range_record else requested_range_name,
            "Range Model ID": range_model,
            "Range Association": _range_reference_family(range_record) if range_record else "",
            "Range Start": start,
            "Range Addresses": addresses,
            "Range End": end,
            "Geometry Signature": geometry_text,
            "Exclusion Pattern": exclusions,
            "Fixed Address Templates": fixed_templates,
            "Options State": option_state,
            "Stored Enabled Options": enabled_options,
            "Review Flags": ", ".join(flags),
            "Notes": "; ".join(notes),
            "_bundle_shape": payload,
            "_bundle_sha256": digest,
        })

    for network in sorted(networks, key=lambda record: (record.grid, str(record.name or ""))):
        linked = list(network.range_templates or [])
        if not linked:
            emit(network, None, status="NETWORK_ONLY")
            continue
        for range_name in linked:
            range_record = ranges_by_grid_name.get((network.grid, str(range_name)))
            if range_record is None:
                emit(network, None, status="MISSING_RANGE_TEMPLATE", requested_range_name=str(range_name))
                continue
            linked_range_keys.add((range_record.grid, str(range_record.name or "")))
            emit(network, range_record, status="LINKED")

    for range_record in sorted(ranges, key=lambda record: (record.grid, str(record.name or ""))):
        key = (range_record.grid, str(range_record.name or ""))
        if key not in linked_range_keys:
            emit(None, range_record, status="ORPHAN_RANGE_TEMPLATE")

    return rows


def build_template_bundle_models(
    bundle_rows: list[dict[str, Any]], grids: list[str]
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in bundle_rows:
        groups[str(row.get("Bundle Model ID") or "")].append(row)

    total_grids = len(set(grids))
    output: list[dict[str, Any]] = []
    for model_id, rows in sorted(groups.items()):
        model_grids = sorted({str(row.get("Grid") or "") for row in rows if row.get("Grid")})
        shapes = { _json(row.get("_bundle_shape")) for row in rows }
        if len(shapes) != 1:
            raise ValueError(f"Bundle model {model_id} has non-identical canonical shapes")
        shape = rows[0].get("_bundle_shape")
        hashes = {str(row.get("_bundle_sha256") or "") for row in rows}
        if len(hashes) != 1:
            raise ValueError(f"Bundle model {model_id} has inconsistent SHA256 evidence")
        output.append({
            "Bundle Model ID": model_id,
            "Provisioning Family": rows[0].get("Provisioning Family"),
            "Bundle Count": len(rows),
            "Grid Count": len(model_grids),
            "Grid Coverage %": round(len(model_grids) * 100.0 / total_grids, 1) if total_grids else None,
            "Grids": ", ".join(model_grids),
            "Network Models": ", ".join(sorted({str(row.get("Network Model ID") or "") for row in rows if row.get("Network Model ID")})),
            "Range Models": ", ".join(sorted({str(row.get("Range Model ID") or "") for row in rows if row.get("Range Model ID")})),
            "Geometry Signature": str(rows[0].get("Geometry Signature") or ""),
            "Network Templates": ", ".join(sorted({str(row.get("Network Template") or "") for row in rows if row.get("Network Template")})),
            "Range Templates": ", ".join(sorted({str(row.get("Range Template") or "") for row in rows if row.get("Range Template")})),
            "Review Flags": ", ".join(sorted({
                flag.strip()
                for row in rows
                for flag in str(row.get("Review Flags") or "").split(",")
                if flag.strip()
            })),
            "Canonical Shape": _json(shape),
            "Full SHA256": next(iter(hashes)),
        })

    # Remove technical private keys before workbook/report consumers see pair rows.
    for row in bundle_rows:
        row.pop("_bundle_shape", None)
        row.pop("_bundle_sha256", None)
    return output

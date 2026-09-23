"""Human-facing NetworkTemplate -> RangeTemplate provisioning bundles."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .topology import DHCPTemplateRecord, MemberAssociation, NetworkTemplateRecord, RangeTemplateRecord


TEMPLATE_BUNDLE_HEADERS = [
    "Grid", "Bundle Status", "Provisioning Family",
    "Network Template", "Network Model ID", "Network Prefix", "Network Member Family",
    "Range Template", "Range Model ID", "Range Association",
    "Range Start", "Range Addresses", "Range End", "Exclusion Pattern",
    "Fixed Address Templates", "Options State", "Stored Enabled Options",
    "Review Flags", "Notes",
]


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


def _range_geometry(
    network: NetworkTemplateRecord | None,
    range_record: RangeTemplateRecord | None,
) -> tuple[str, str, str, str]:
    if range_record is None:
        return "", "", "", ""
    offset = range_record.offset
    count = range_record.number_of_addresses
    start = "" if offset is None else ("FIRST_USABLE" if offset == 1 else f"HOST_OFFSET_{offset}")
    addresses = "" if count is None else str(count)
    end = ""
    exclusions = []

    total = None
    if network is not None and isinstance(network.netmask, int) and 0 <= network.netmask <= 32:
        total = 1 << (32 - network.netmask)
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
            exclusions.append(
                f"offset {ex_offset}, count {ex_count}, {total - 1 - ex_offset} before broadcast"
            )
        else:
            exclusions.append(f"offset {ex_offset}, count {ex_count}")
    return start, addresses, end, "; ".join(exclusions) if exclusions else "NONE"


def _options_summary(record: DHCPTemplateRecord | None) -> tuple[str, str, list[str]]:
    if record is None:
        return "", "", []
    enabled = [
        option for option in (record.options or [])
        if option.use_option is True and option.value not in (None, "")
    ]
    option_labels = [
        str(option.name or option.num or "?")
        for option in enabled
    ]
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
        family = _provisioning_family(network, range_record)
        if family == "MIXED_OR_INCONSISTENT":
            flags.append("NETWORK_RANGE_ASSOCIATION_MISMATCH")
    if range_record is not None:
        if range_record.server_association_type == "NONE" and (
            range_record.member is not None
            or range_record.ms_server is not None
            or range_record.failover_association
        ):
            flags.append("ASSOCIATION_NONE_WITH_SERVER_REFERENCE")
    return sorted(set(flags))


def build_template_bundles(
    records: list[Any],
    assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return one row per linked NetworkTemplate/RangeTemplate pair plus orphans."""
    model_by_key = _assignment_index(assignments)
    networks = [record for record in records if isinstance(record, NetworkTemplateRecord)]
    ranges = [record for record in records if isinstance(record, RangeTemplateRecord)]
    ranges_by_grid_name = {
        (record.grid, str(record.name or "")): record
        for record in ranges
    }
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
        start, addresses, end, exclusions = _range_geometry(network, range_record)
        network_model = model_by_key.get(_record_key(network), "") if network else ""
        range_model = model_by_key.get(_record_key(range_record), "") if range_record else ""
        fixed_templates = ", ".join(network.fixed_address_templates or []) if network else ""
        notes: list[str] = []
        if status == "MISSING_RANGE_TEMPLATE":
            notes.append(f"Linked RangeTemplate not collected/found: {requested_range_name}")
        if status == "ORPHAN_RANGE_TEMPLATE":
            notes.append("RangeTemplate is not referenced by any collected NetworkTemplate.")
        rows.append({
            "Grid": network.grid if network else range_record.grid if range_record else "",
            "Bundle Status": status,
            "Provisioning Family": _provisioning_family(network, range_record),
            "Network Template": network.name or "" if network else "",
            "Network Model ID": network_model,
            "Network Prefix": f"/{network.netmask}" if network and network.netmask is not None else "",
            "Network Member Family": _member_family(network.members) if network else "",
            "Range Template": (
                range_record.name or "" if range_record else requested_range_name
            ),
            "Range Model ID": range_model,
            "Range Association": _range_reference_family(range_record) if range_record else "",
            "Range Start": start,
            "Range Addresses": addresses,
            "Range End": end,
            "Exclusion Pattern": exclusions,
            "Fixed Address Templates": fixed_templates,
            "Options State": option_state,
            "Stored Enabled Options": enabled_options,
            "Review Flags": ", ".join(flags),
            "Notes": "; ".join(notes),
        })

    for network in sorted(networks, key=lambda record: (record.grid, str(record.name or ""))):
        linked = list(network.range_templates or [])
        if not linked:
            emit(network, None, status="NETWORK_ONLY")
            continue
        for range_name in linked:
            range_record = ranges_by_grid_name.get((network.grid, str(range_name)))
            if range_record is None:
                emit(
                    network, None, status="MISSING_RANGE_TEMPLATE",
                    requested_range_name=str(range_name),
                )
                continue
            linked_range_keys.add((range_record.grid, str(range_record.name or "")))
            emit(network, range_record, status="LINKED")

    for range_record in sorted(ranges, key=lambda record: (record.grid, str(record.name or ""))):
        key = (range_record.grid, str(range_record.name or ""))
        if key not in linked_range_keys:
            emit(None, range_record, status="ORPHAN_RANGE_TEMPLATE")

    return rows

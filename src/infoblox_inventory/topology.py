"""Typed, stored configuration for reusable DHCP objects; no inheritance resolution.

Field types follow the LAB WAPI 2.13.7 runtime schemas. Missing optional values
remain None. Original responses, including unfamiliar fields, remain available
on every record for troubleshooting.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, ClassVar

from .models import CollectionResult


TOPOLOGY_SHEETS = {
    "dhcpfailover": "DHCP_Failover",
    "networktemplate": "Network_Templates",
    "rangetemplate": "Range_Templates",
    "fixedaddresstemplate": "Fixed_Address_Templates",
    "dhcpoptionspace": "Option_Spaces",
    "dhcpoptiondefinition": "Option_Definitions",
}


@dataclass(kw_only=True)
class DHCPOption:
    name: str | None = None
    num: int | None = None
    vendor_class: str | None = None
    value: str | None = None
    use_option: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class MemberAssociation:
    """Observed DHCP-member/MS-server fields; does not infer the member type."""

    name: str | None = None
    ipv4addr: str | None = None
    ipv6addr: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class MSServerAssociation:
    ipv4addr: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class RangeExclusion:
    offset: int | None = None
    number_of_addresses: int | None = None
    comment: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class TopologyRecord:
    object_type: ClassVar[str]
    data_representation: ClassVar[str] = "RAW_CONFIGURATION"
    grid: str
    object_ref: str | None = None
    name: str | None = None
    status: str = "COMPLETE"
    issues: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def to_excel(self) -> dict[str, Any]:
        row = {
            "grid": self.grid, "object_type": self.object_type,
            "object_ref": self.object_ref, "name": self.name,
            "data_representation": self.data_representation,
            "normalization_status": self.status, "issues": list(self.issues),
        }
        row.update({item.name: _excel_value(getattr(self, item.name))
                    for item in fields(self)
                    if item.name not in {"grid", "object_ref", "name", "status", "issues", "raw"}})
        return row


@dataclass(kw_only=True)
class DHCPFailoverRecord(TopologyRecord):
    object_type: ClassVar[str] = "dhcpfailover"
    comment: str | None = None
    association_type: str | None = None
    primary: str | None = None
    primary_server_type: str | None = None
    primary_state: str | None = None
    secondary: str | None = None
    secondary_server_type: str | None = None
    secondary_state: str | None = None
    failover_port: int | None = None
    use_failover_port: bool | None = None
    load_balance_split: int | None = None
    max_client_lead_time: int | None = None
    max_load_balance_delay: int | None = None
    max_response_delay: int | None = None
    max_unacked_updates: int | None = None
    recycle_leases: bool | None = None
    use_recycle_leases: bool | None = None
    ms_association_mode: str | None = None
    ms_enable_authentication: bool | None = None
    ms_enable_switchover_interval: bool | None = None
    ms_failover_mode: str | None = None
    ms_failover_partner: str | None = None
    ms_hotstandby_partner_role: str | None = None
    ms_is_conflict: bool | None = None
    ms_previous_state: str | None = None
    ms_server: str | None = None
    ms_state: str | None = None
    ms_switchover_interval: int | None = None
    use_ms_switchover_interval: bool | None = None


@dataclass(kw_only=True)
class DHCPTemplateRecord(TopologyRecord):
    comment: str | None = None
    options: list[DHCPOption] | None = None
    use_options: bool | None = None
    bootfile: str | None = None
    use_bootfile: bool | None = None
    bootserver: str | None = None
    use_bootserver: bool | None = None
    nextserver: str | None = None
    use_nextserver: bool | None = None
    deny_bootp: bool | None = None
    use_deny_bootp: bool | None = None
    enable_pxe_lease_time: bool | None = None
    pxe_lease_time: int | None = None
    use_pxe_lease_time: bool | None = None
    ignore_dhcp_option_list_request: bool | None = None
    use_ignore_dhcp_option_list_request: bool | None = None


@dataclass(kw_only=True)
class NetworkTemplateRecord(DHCPTemplateRecord):
    object_type: ClassVar[str] = "networktemplate"
    netmask: int | None = None
    allow_any_netmask: bool | None = None
    members: list[MemberAssociation] | None = None
    delegated_member: MemberAssociation | None = None
    range_templates: list[str] | None = None
    fixed_address_templates: list[str] | None = None
    authority: bool | None = None
    use_authority: bool | None = None
    lease_scavenge_time: int | None = None
    use_lease_scavenge_time: bool | None = None
    recycle_leases: bool | None = None
    use_recycle_leases: bool | None = None


@dataclass(kw_only=True)
class RangeTemplateRecord(DHCPTemplateRecord):
    object_type: ClassVar[str] = "rangetemplate"
    offset: int | None = None
    number_of_addresses: int | None = None
    server_association_type: str | None = None
    member: MemberAssociation | None = None
    ms_server: MSServerAssociation | None = None
    delegated_member: MemberAssociation | None = None
    failover_association: str | None = None
    exclude: list[RangeExclusion] | None = None
    lease_scavenge_time: int | None = None
    use_lease_scavenge_time: bool | None = None
    recycle_leases: bool | None = None
    use_recycle_leases: bool | None = None


@dataclass(kw_only=True)
class FixedAddressTemplateRecord(DHCPTemplateRecord):
    object_type: ClassVar[str] = "fixedaddresstemplate"
    offset: int | None = None
    number_of_addresses: int | None = None


@dataclass(kw_only=True)
class DHCPOptionSpaceRecord(TopologyRecord):
    object_type: ClassVar[str] = "dhcpoptionspace"
    comment: str | None = None
    option_definitions: list[str] | None = None
    space_type: str | None = None


@dataclass(kw_only=True)
class DHCPOptionDefinitionRecord(TopologyRecord):
    object_type: ClassVar[str] = "dhcpoptiondefinition"
    code: int | None = None
    space: str | None = None
    type: str | None = None


TypedTopologyRecord = (DHCPFailoverRecord | NetworkTemplateRecord | RangeTemplateRecord
                       | FixedAddressTemplateRecord | DHCPOptionSpaceRecord
                       | DHCPOptionDefinitionRecord)

_RECORD_CLASSES = {record.object_type: record for record in (
    DHCPFailoverRecord, NetworkTemplateRecord, RangeTemplateRecord,
    FixedAddressTemplateRecord, DHCPOptionSpaceRecord, DHCPOptionDefinitionRecord,
)}

# These types were observed in the runtime schemas, including signed lease
# scavenge times. Class annotations alone cannot distinguish uint from int.
_UINT_FIELDS = {
    "num", "code", "netmask", "offset", "number_of_addresses", "pxe_lease_time",
    "failover_port", "load_balance_split", "max_client_lead_time",
    "max_load_balance_delay", "max_response_delay", "max_unacked_updates",
    "ms_switchover_interval",
}
_BOOL_FIELDS = {
    "use_option", "use_options", "use_bootfile", "use_bootserver", "use_nextserver",
    "deny_bootp", "use_deny_bootp", "enable_pxe_lease_time", "use_pxe_lease_time",
    "ignore_dhcp_option_list_request", "use_ignore_dhcp_option_list_request",
    "allow_any_netmask", "authority", "use_authority", "use_lease_scavenge_time",
    "recycle_leases", "use_recycle_leases", "use_failover_port",
    "ms_enable_authentication", "ms_enable_switchover_interval", "ms_is_conflict",
    "use_ms_switchover_interval",
}
_STRING_ARRAY_FIELDS = {"range_templates", "fixed_address_templates", "option_definitions"}
_STRUCT_FIELDS = {
    "options": (DHCPOption, True),
    "members": (MemberAssociation, True),
    "member": (MemberAssociation, False),
    "delegated_member": (MemberAssociation, False),
    "exclude": (RangeExclusion, True),
}
_META_FIELDS = {"grid", "object_ref", "status", "issues", "raw", "extra_fields"}


def _excel_value(value: Any) -> Any:
    if is_dataclass(value):
        return {item.name: _excel_value(getattr(value, item.name)) for item in fields(value)
                if item.name != "raw"}
    if isinstance(value, list):
        return [_excel_value(item) for item in value]
    return deepcopy(value)


def _scalar(value: Any, name: str, path: str, issues: list[str]) -> Any:
    if name in _BOOL_FIELDS:
        expected, valid = "boolean", type(value) is bool
    elif name in _UINT_FIELDS:
        expected, valid = "unsigned integer", type(value) is int and value >= 0
    elif name == "lease_scavenge_time":
        expected, valid = "integer", type(value) is int
    else:
        expected, valid = "string", isinstance(value, str)
    if not valid:
        issues.append(f"{path}: expected {expected}, got {type(value).__name__}; retained in raw")
        return None
    return value


def _parse_fields(raw: dict[str, Any], cls: type, issues: list[str], path: str = "") -> dict[str, Any]:
    names = {item.name for item in fields(cls)} - _META_FIELDS
    values: dict[str, Any] = {}
    for name in sorted(names):
        if name not in raw:
            continue
        value = raw[name]
        field_path = f"{path}.{name}" if path else name
        nested = _STRUCT_FIELDS.get(name)
        # The failover ms_server is a string; range-template ms_server is a struct.
        if name == "ms_server" and cls is RangeTemplateRecord:
            nested = (MSServerAssociation, False)
        if nested:
            nested_cls, array = nested
            if array:
                if not isinstance(value, list):
                    issues.append(f"{field_path}: expected array, got {type(value).__name__}; retained in raw")
                    values[name] = None
                    continue
                values[name] = []
                for index, item in enumerate(value):
                    parsed = _parse_struct(item, nested_cls, issues, f"{field_path}[{index}]")
                    if parsed is not None:
                        values[name].append(parsed)
            else:
                values[name] = _parse_struct(value, nested_cls, issues, field_path)
        elif name in _STRING_ARRAY_FIELDS:
            if not isinstance(value, list):
                issues.append(f"{field_path}: expected string array, got {type(value).__name__}; retained in raw")
                values[name] = None
            else:
                values[name] = []
                for index, item in enumerate(value):
                    parsed = _scalar(item, name, f"{field_path}[{index}]", issues)
                    if parsed is not None:
                        values[name].append(parsed)
        else:
            values[name] = _scalar(value, name, field_path, issues)
    values["raw"] = deepcopy(raw)
    values["extra_fields"] = deepcopy({name: value for name, value in raw.items()
                                      if name not in names and name != "_ref"})
    return values


def _parse_struct(value: Any, cls: type, issues: list[str], path: str) -> Any:
    if not isinstance(value, dict):
        issues.append(f"{path}: expected object, got {type(value).__name__}; retained in raw")
        return None
    return cls(**_parse_fields(value, cls, issues, path))


def normalize_topology(result: CollectionResult) -> list[TypedTopologyRecord]:
    """Normalize only the six requested object types and only their RAW evidence."""
    records: list[TypedTopologyRecord] = []
    for object_type, cls in _RECORD_CLASSES.items():
        for raw in result.records.get(object_type, []):
            issues: list[str] = []
            values = _parse_fields(raw, cls, issues)
            object_ref = (_scalar(raw["_ref"], "_ref", "_ref", issues)
                          if "_ref" in raw else None)
            records.append(cls(grid=result.grid, object_ref=object_ref, issues=issues,
                               status="PARTIAL" if issues else "COMPLETE", **values))
    return records


def topology_headers(object_type: str) -> list[str]:
    return list(_RECORD_CLASSES[object_type](grid="").to_excel())


def topology_excel_rows(records: list[TypedTopologyRecord]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {key: [] for key in TOPOLOGY_SHEETS}
    for record in records:
        rows[record.object_type].append(record.to_excel())
    return rows


def topology_option_rows(records: list[TypedTopologyRecord]) -> list[dict[str, Any]]:
    """Stored template options/use flags, deliberately without effective values."""
    rows = []
    for record in records:
        if not isinstance(record, DHCPTemplateRecord):
            continue
        for option in record.options or []:
            rows.append({
                "grid": record.grid, "object_type": record.object_type,
                "object_ref": record.object_ref, "name": record.name,
                "data_representation": record.data_representation,
                "normalization_status": record.status, "issues": list(record.issues),
                "option_name": option.name, "code": option.num,
                "vendor": option.vendor_class, "stored_value": option.value,
                "use_option": option.use_option, "use_options": record.use_options,
                "extra_fields": deepcopy(option.extra_fields),
            })
    return rows


def topology_coverage(records: list[TypedTopologyRecord]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[TypedTopologyRecord]] = defaultdict(list)
    for record in records:
        groups[(record.grid, record.object_type)].append(record)
    rows = []
    for (grid, object_type), group in sorted(groups.items()):
        partial = sum(record.status == "PARTIAL" for record in group)
        notes = [f"{record.object_ref or record.name or '(unnamed)'}: {issue}"
                 for record in group for issue in record.issues]
        rows.append({
            "Grid": grid, "Area": TOPOLOGY_SHEETS[object_type].replace("_", " "),
            "Object Type": object_type, "Query": "normalization",
            "Collection Status": "PARTIAL" if partial else "COMPLETE",
            "Objects Found": len(group), "Partial Objects": partial,
            "Notes": "; ".join(notes) if notes else "Stored configuration; no inheritance resolution.",
        })
    return rows

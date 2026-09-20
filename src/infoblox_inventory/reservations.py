"""Typed DHCP reservation/filter configuration from LAB WAPI 2.13.7 schemas.

Only stored configuration is represented here. References are not resolved,
filter names imply no policy, and DDNS/EA fields are retained as evidence only.
Every object and nested structure keeps a separate deep copy of its raw JSON.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from types import UnionType
from typing import Any, ClassVar, get_args, get_origin, get_type_hints

from .models import CollectionResult
from .topology import DHCPOption, MemberAssociation, MSServerAssociation


RESERVATION_SHEETS = {
    "fixedaddress": "Fixed_Reservations",
    "record:host": "Host_DHCP_Context",
    "record:host_ipv4addr": "Host_IPv4_DHCP",
    "roaminghost": "Roaming_Hosts",
    "superhost": "Superhost_DHCP",
    "superhostchild": "Superhost_Fixed_Links",
    "filtermac": "MAC_Filters",
    "macfilteraddress": "MAC_Filter_Addresses",
    "filteroption": "Option_Filters",
    "filterrelayagent": "Relay_Agent_Filters",
    "filterfingerprint": "Fingerprint_Filters",
    "filternac": "NAC_Filters",
}


@dataclass(kw_only=True)
class StoredStructure:
    raw: dict[str, Any] = field(default_factory=dict)
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class MSDHCPOption(StoredStructure):
    name: str | None = None
    num: int | None = None
    vendor_class: str | None = None
    user_class: str | None = None
    value: str | None = None
    type: str | None = None


@dataclass(kw_only=True)
class LogicFilterRule(StoredStructure):
    filter: str | None = None
    type: str | None = None


@dataclass(kw_only=True)
class CloudInfo(StoredStructure):
    delegated_member: MemberAssociation | None = None
    delegated_scope: str | None = None
    delegated_root: str | None = None
    owned_by_adaptor: bool | None = None
    usage: str | None = None
    tenant: str | None = None
    mgmt_platform: str | None = None
    authority_type: str | None = None


@dataclass(kw_only=True)
class AssociatedObject(StoredStructure):
    """An embedded union object whose contents remain unclassified evidence."""

    object_ref: str | None = None


@dataclass(kw_only=True)
class DHCPBootConfiguration:
    bootfile: str | None = None
    bootserver: str | None = None
    nextserver: str | None = None
    deny_bootp: bool | None = None
    enable_pxe_lease_time: bool | None = None
    pxe_lease_time: int | None = None
    use_bootfile: bool | None = None
    use_bootserver: bool | None = None
    use_nextserver: bool | None = None
    use_deny_bootp: bool | None = None
    use_pxe_lease_time: bool | None = None


@dataclass(kw_only=True)
class HostIPv4Data(StoredStructure, DHCPBootConfiguration):
    object_ref: str | None = None
    ipv4addr: str | None = None
    mac: str | None = None
    host: str | None = None
    network: str | None = None
    network_view: str | None = None
    configure_for_dhcp: bool | None = None
    match_client: str | None = None
    options: list[DHCPOption] | None = None
    logic_filter_rules: list[LogicFilterRule] | None = None
    is_invalid_mac: bool | None = None
    reserved_interface: str | None = None
    ignore_client_requested_options: bool | None = None
    use_options: bool | None = None
    use_logic_filter_rules: bool | None = None
    use_ignore_client_requested_options: bool | None = None

    @property
    def dhcp_configuration_status(self) -> str:
        if self.configure_for_dhcp is None:
            return "PARTIAL"
        return "COMPLETE" if self.configure_for_dhcp else "NOT_CONFIGURED"


@dataclass(kw_only=True)
class ReservationRecord(StoredStructure):
    object_type: ClassVar[str]
    data_representation: ClassVar[str] = "RAW_CONFIGURATION"
    grid: str
    object_ref: str | None = None
    name: str | None = None
    status: str = "COMPLETE"
    issues: list[str] = field(default_factory=list)

    def to_excel(self) -> dict[str, Any]:
        row = {
            "grid": self.grid, "object_type": self.object_type,
            "object_ref": self.object_ref, "name": self.name,
            "data_representation": self.data_representation,
            "normalization_status": self.status, "issues": list(self.issues),
        }
        row.update({item.name: _excel_value(getattr(self, item.name))
                    for item in fields(self) if item.name not in _META_FIELDS | {"name"}})
        if isinstance(self, (HostRecord, HostIPv4Record)):
            row["dhcp_configuration_status"] = self.dhcp_configuration_status
        row["extra_fields"] = deepcopy(self.extra_fields)
        return row


@dataclass(kw_only=True)
class FixedAddressRecord(ReservationRecord, DHCPBootConfiguration):
    object_type: ClassVar[str] = "fixedaddress"
    ipv4addr: str | None = None
    mac: str | None = None
    dhcp_client_identifier: str | None = None
    client_identifier_prepend_zero: bool | None = None
    network: str | None = None
    network_view: str | None = None
    match_client: str | None = None
    agent_circuit_id: str | None = None
    agent_remote_id: str | None = None
    enable_ddns: bool | None = None
    ddns_hostname: str | None = None
    ddns_domainname: str | None = None
    options: list[DHCPOption] | None = None
    ms_options: list[MSDHCPOption] | None = None
    ms_server: MSServerAssociation | None = None
    cloud_info: CloudInfo | None = None
    comment: str | None = None
    extattrs: dict[str, Any] | None = None
    disable: bool | None = None
    is_invalid_mac: bool | None = None
    reserved_interface: str | None = None
    logic_filter_rules: list[LogicFilterRule] | None = None
    ignore_dhcp_option_list_request: bool | None = None
    use_enable_ddns: bool | None = None
    use_ddns_domainname: bool | None = None
    use_options: bool | None = None
    use_ms_options: bool | None = None
    use_logic_filter_rules: bool | None = None
    use_ignore_dhcp_option_list_request: bool | None = None


@dataclass(kw_only=True)
class HostRecord(ReservationRecord):
    object_type: ClassVar[str] = "record:host"
    network_view: str | None = None
    disable: bool | None = None
    comment: str | None = None
    extattrs: dict[str, Any] | None = None
    ipv4addrs: list[str | HostIPv4Data] | None = None

    @property
    def dhcp_configuration_status(self) -> str:
        if self.ipv4addrs is None or any(issue.startswith("ipv4addrs") for issue in self.issues):
            return "PARTIAL"
        if any(isinstance(item, str) or item.configure_for_dhcp is None for item in self.ipv4addrs):
            return "PARTIAL"
        return ("COMPLETE" if any(item.configure_for_dhcp for item in self.ipv4addrs)
                else "NOT_CONFIGURED")


@dataclass(kw_only=True)
class HostIPv4Record(ReservationRecord, HostIPv4Data):
    object_type: ClassVar[str] = "record:host_ipv4addr"


@dataclass(kw_only=True)
class RoamingHostRecord(ReservationRecord, DHCPBootConfiguration):
    """Roaming host configuration; no fixed address is inferred."""

    object_type: ClassVar[str] = "roaminghost"
    address_type: str | None = None
    mac: str | None = None
    dhcp_client_identifier: str | None = None
    client_identifier_prepend_zero: bool | None = None
    match_client: str | None = None
    network_view: str | None = None
    enable_ddns: bool | None = None
    ddns_hostname: str | None = None
    ddns_domainname: str | None = None
    force_roaming_hostname: bool | None = None
    options: list[DHCPOption] | None = None
    comment: str | None = None
    extattrs: dict[str, Any] | None = None
    disable: bool | None = None
    ignore_dhcp_option_list_request: bool | None = None
    ipv6_duid: str | None = None
    ipv6_mac_address: str | None = None
    ipv6_match_option: str | None = None
    ipv6_options: list[DHCPOption] | None = None
    preferred_lifetime: int | None = None
    valid_lifetime: int | None = None
    use_enable_ddns: bool | None = None
    use_ddns_domainname: bool | None = None
    use_options: bool | None = None
    use_ignore_dhcp_option_list_request: bool | None = None
    use_ipv6_options: bool | None = None
    use_preferred_lifetime: bool | None = None
    use_valid_lifetime: bool | None = None


@dataclass(kw_only=True)
class SuperhostRecord(ReservationRecord):
    object_type: ClassVar[str] = "superhost"
    comment: str | None = None
    disabled: bool | None = None
    dhcp_associated_objects: list[str | AssociatedObject] | None = None


@dataclass(kw_only=True)
class SuperhostChildRecord(ReservationRecord):
    object_type: ClassVar[str] = "superhostchild"
    comment: str | None = None
    data: str | None = None
    disabled: bool | None = None
    network_view: str | None = None
    parent: str | None = None
    record_parent: str | None = None
    type: str | None = None
    associated_object: str | None = None


@dataclass(kw_only=True)
class MACFilterRecord(ReservationRecord):
    object_type: ClassVar[str] = "filtermac"
    comment: str | None = None
    disable: bool | None = None
    default_mac_address_expiration: int | None = None
    enforce_expiration_times: bool | None = None
    never_expires: bool | None = None
    lease_time: int | None = None
    options: list[DHCPOption] | None = None


@dataclass(kw_only=True)
class MACFilterAddressRecord(ReservationRecord):
    object_type: ClassVar[str] = "macfilteraddress"
    mac: str | None = None
    filter: str | None = None
    comment: str | None = None
    authentication_time: int | None = None
    expiration_time: int | None = None
    never_expires: bool | None = None
    fingerprint: str | None = None
    is_registered_user: bool | None = None


@dataclass(kw_only=True)
class OptionFilterRecord(ReservationRecord):
    object_type: ClassVar[str] = "filteroption"
    comment: str | None = None
    expression: str | None = None
    apply_as_class: bool | None = None
    option_space: str | None = None
    option_list: list[DHCPOption] | None = None
    lease_time: int | None = None
    bootfile: str | None = None
    bootserver: str | None = None
    next_server: str | None = None
    pxe_lease_time: int | None = None


@dataclass(kw_only=True)
class RelayAgentFilterRecord(ReservationRecord):
    object_type: ClassVar[str] = "filterrelayagent"
    comment: str | None = None
    is_circuit_id: str | None = None
    circuit_id_name: str | None = None
    is_circuit_id_substring: bool | None = None
    circuit_id_substring_offset: int | None = None
    circuit_id_substring_length: int | None = None
    is_remote_id: str | None = None
    remote_id_name: str | None = None
    is_remote_id_substring: bool | None = None
    remote_id_substring_offset: int | None = None
    remote_id_substring_length: int | None = None


@dataclass(kw_only=True)
class FingerprintFilterRecord(ReservationRecord):
    object_type: ClassVar[str] = "filterfingerprint"
    comment: str | None = None
    fingerprint: list[str] | None = None


@dataclass(kw_only=True)
class NACFilterRecord(ReservationRecord):
    object_type: ClassVar[str] = "filternac"
    comment: str | None = None
    expression: str | None = None
    lease_time: int | None = None
    options: list[DHCPOption] | None = None


TypedReservationRecord = (FixedAddressRecord | HostRecord | HostIPv4Record | RoamingHostRecord
                          | SuperhostRecord | SuperhostChildRecord | MACFilterRecord
                          | MACFilterAddressRecord | OptionFilterRecord | RelayAgentFilterRecord
                          | FingerprintFilterRecord | NACFilterRecord)
_RECORD_CLASSES = {cls.object_type: cls for cls in (
    FixedAddressRecord, HostRecord, HostIPv4Record, RoamingHostRecord, SuperhostRecord,
    SuperhostChildRecord, MACFilterRecord, MACFilterAddressRecord, OptionFilterRecord,
    RelayAgentFilterRecord, FingerprintFilterRecord, NACFilterRecord,
)}
_META_FIELDS = {"grid", "object_ref", "status", "issues", "raw", "extra_fields"}
_TIMESTAMP_FIELDS = {"authentication_time", "expiration_time"}
_OPTION_FIELDS = ("options", "option_list", "ms_options", "ipv6_options")


def _excel_value(value: Any) -> Any:
    if is_dataclass(value):
        return {item.name: _excel_value(getattr(value, item.name))
                for item in fields(value) if item.name != "raw"}
    if isinstance(value, list):
        return [_excel_value(item) for item in value]
    return deepcopy(value)


def _bad(value: Any, expected: str, path: str, issues: list[str]) -> None:
    issues.append(f"{path}: expected {expected}, got {type(value).__name__}; retained in raw")


def _parse_value(value: Any, annotation: Any, name: str, path: str, issues: list[str]) -> Any:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is UnionType:
        candidates = [candidate for candidate in args if candidate is not type(None)]
        if len(candidates) == 1:
            return _parse_value(value, candidates[0], name, path, issues)
        # The only wire unions selected here are object references or embedded objects.
        if isinstance(value, str) and str in candidates:
            return value
        nested = next((candidate for candidate in candidates if is_dataclass(candidate)), None)
        if isinstance(value, dict) and nested:
            return _parse_structure(value, nested, issues, path)
        _bad(value, "object reference string or embedded object", path, issues)
        return None
    if origin is list:
        if not isinstance(value, list):
            _bad(value, "array", path, issues)
            return None
        values = []
        for index, item in enumerate(value):
            parsed = _parse_value(item, args[0], name, f"{path}[{index}]", issues)
            if parsed is not None:
                values.append(parsed)
        return values
    if origin is dict:
        if not isinstance(value, dict):
            _bad(value, "object", path, issues)
            return None
        return deepcopy(value)
    if is_dataclass(annotation):
        if isinstance(value, dict):
            return _parse_structure(value, annotation, issues, path)
        _bad(value, "object", path, issues)
        return None
    if annotation is bool:
        valid, expected = type(value) is bool, "boolean"
    elif annotation is int:
        valid = type(value) is int and (name in _TIMESTAMP_FIELDS or value >= 0)
        expected = "timestamp integer" if name in _TIMESTAMP_FIELDS else "unsigned integer"
    else:
        valid, expected = isinstance(value, str), "string"
    if not valid:
        _bad(value, expected, path, issues)
        return None
    return value


def _parse_structure(raw: dict[str, Any], cls: type, issues: list[str], path: str = "",
                     grid: str | None = None) -> Any:
    names = {item.name for item in fields(cls)} - _META_FIELDS
    annotations = get_type_hints(cls)
    values: dict[str, Any] = {}
    for name in sorted(names):
        if name in raw:
            field_path = f"{path}.{name}" if path else name
            values[name] = _parse_value(raw[name], annotations[name], name, field_path, issues)
    if "object_ref" in annotations:
        values["object_ref"] = (_parse_value(raw["_ref"], str, "_ref",
                                            f"{path}._ref" if path else "_ref", issues)
                                if "_ref" in raw else None)
    values["raw"] = deepcopy(raw)
    values["extra_fields"] = deepcopy({key: value for key, value in raw.items()
                                      if key not in names and key != "_ref"})
    if grid is not None:
        values.update(grid=grid, issues=issues, status="PARTIAL" if issues else "COMPLETE")
    return cls(**values)


def normalize_reservations(result: CollectionResult) -> list[TypedReservationRecord]:
    """Read RAW evidence only; never substitute or infer effective values."""
    records: list[TypedReservationRecord] = []
    for object_type, cls in _RECORD_CLASSES.items():
        for raw in result.records.get(object_type, []):
            issues: list[str] = []
            records.append(_parse_structure(raw, cls, issues, grid=result.grid))
    return records


def reservation_headers(object_type: str) -> list[str]:
    return list(_RECORD_CLASSES[object_type](grid="").to_excel())


def reservation_excel_rows(records: list[TypedReservationRecord]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {key: [] for key in RESERVATION_SHEETS}
    for record in records:
        rows[record.object_type].append(record.to_excel())
    return rows


def _row_context(record: ReservationRecord) -> dict[str, Any]:
    return {
        "grid": record.grid, "object_type": record.object_type,
        "object_ref": record.object_ref, "name": record.name,
        "data_representation": record.data_representation,
        "normalization_status": record.status, "issues": list(record.issues),
    }


def _source_items(source: Any, field_name: str) -> list[tuple[int | None, Any]]:
    """Locate parsed items in RAW order, including repeated references/objects.

    Malformed items may have been omitted from the typed list. Their positions
    must still count when an exported row identifies a source-array index.
    An index is unavailable for a manually constructed/changed typed item that
    has no matching RAW evidence; never substitute its compressed list index.
    """
    original = source.raw.get(field_name, [])
    if not isinstance(original, list):
        original = []
    cursor = 0
    rows = []
    for value in getattr(source, field_name, None) or []:
        evidence = value.raw if is_dataclass(value) else value
        index = next((position for position in range(cursor, len(original))
                      if type(original[position]) is type(evidence)
                      and original[position] == evidence), None)
        if index is not None:
            cursor = index + 1
        rows.append((index, value))
    return rows


def reservation_option_rows(records: list[TypedReservationRecord]) -> list[dict[str, Any]]:
    """One row per stored DHCP option, including options embedded in a host."""
    rows = []
    for record in records:
        sources: list[tuple[str, Any]] = [("", record)]
        if isinstance(record, HostRecord):
            sources.extend((f"ipv4addrs[{index if index is not None else 'unavailable'}].", item)
                           for index, item in _source_items(record, "ipv4addrs")
                           if isinstance(item, HostIPv4Data))
        for prefix, source in sources:
            for option_field in _OPTION_FIELDS:
                for index, option in _source_items(source, option_field):
                    rows.append({
                        **_row_context(record), "option_field": prefix + option_field,
                        "option_index": index, "option_name": option.name,
                        "code": option.num, "vendor": option.vendor_class,
                        "user_class": getattr(option, "user_class", None),
                        "option_type": getattr(option, "type", None), "stored_value": option.value,
                        "use_option": getattr(option, "use_option", None),
                        "use_options": getattr(source, "use_" + option_field, None),
                        "extra_fields": deepcopy(option.extra_fields),
                    })
    return rows


def reservation_relationship_rows(records: list[TypedReservationRecord]) -> list[dict[str, Any]]:
    """Expose configured relationships without evaluating or resolving policy."""
    rows = []

    def add(record: ReservationRecord, relationship: str, value: Any,
            index: int | None = None, rule_type: str | None = None,
            use_rules: bool | None = None) -> None:
        raw_value = deepcopy(value.raw) if is_dataclass(value) else deepcopy(value)
        target = (getattr(value, "object_ref", None) if is_dataclass(value)
                  else value if isinstance(value, str) else None)
        if isinstance(value, LogicFilterRule):
            target = value.filter
        rows.append({
            **_row_context(record), "relationship_field": relationship,
            "relationship_index": index, "target": target,
            "configured_rule_type": rule_type, "use_logic_filter_rules": use_rules,
            "relationship_data": raw_value,
            "interpretation": "Configured reference/data; policy and target resolution not assessed.",
        })

    for record in records:
        for index, rule in _source_items(record, "logic_filter_rules"):
            add(record, "logic_filter_rules", rule, index, rule.type,
                getattr(record, "use_logic_filter_rules", None))
        if isinstance(record, MACFilterAddressRecord) and record.filter is not None:
            add(record, "filter", record.filter)
        if isinstance(record, HostIPv4Record) and record.host is not None:
            add(record, "host", record.host)
        if isinstance(record, HostRecord):
            for index, item in _source_items(record, "ipv4addrs"):
                add(record, "ipv4addrs", item, index)
                if isinstance(item, HostIPv4Data):
                    for rule_index, rule in _source_items(item, "logic_filter_rules"):
                        raw_index = index if index is not None else "unavailable"
                        add(record, f"ipv4addrs[{raw_index}].logic_filter_rules", rule,
                            rule_index, rule.type, item.use_logic_filter_rules)
        if isinstance(record, SuperhostRecord):
            for index, item in _source_items(record, "dhcp_associated_objects"):
                add(record, "dhcp_associated_objects", item, index)
        if isinstance(record, SuperhostChildRecord):
            for name in ("parent", "record_parent", "associated_object"):
                value = getattr(record, name)
                if value is not None:
                    add(record, name, value)
    return rows


def reservation_coverage(records: list[TypedReservationRecord]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[TypedReservationRecord]] = defaultdict(list)
    for record in records:
        groups[(record.grid, record.object_type)].append(record)
    rows = []
    for (grid, object_type), group in sorted(groups.items()):
        partial = sum(record.status == "PARTIAL" for record in group)
        area = ("DHCP filters and MAC filters" if object_type.startswith("filter")
                or object_type == "macfilteraddress" else "Fixed addresses and reservations")
        notes = [f"{record.object_ref or record.name or '(unnamed)'}: {issue}"
                 for record in group for issue in record.issues]
        rows.append({
            "Grid": grid, "Area": area, "Object": object_type, "Query": "normalization",
            "Collection Status": "PARTIAL" if partial else "COMPLETE",
            "Objects Found": len(group), "Partial Objects": partial,
            "Notes": "; ".join(notes) if notes else
            "Stored configuration; policy meaning, target resolution and inheritance are not inferred.",
        })
        if object_type in {"record:host", "record:host_ipv4addr"}:
            statuses = {record.dhcp_configuration_status for record in group}
            status = ("PARTIAL" if "PARTIAL" in statuses else
                      "COMPLETE" if "COMPLETE" in statuses else "NOT_CONFIGURED")
            rows.append({
                "Grid": grid, "Area": area, "Object": object_type,
                "Query": "dhcp_configuration", "Collection Status": status,
                "Objects Found": len(group),
                "Notes": "IPv4 only, based on explicit configure_for_dhcp flags; references are not "
                         "resolved and DHCPv6 configuration is not assessed.",
            })
    return rows

"""Bounded reservation/filter fields verified in LAB WAPI 2.13.7, 2026-09-20.

Reservation DDNS/EA fields are stored metadata only. No credential fields are selected.
Override flags continue to come from runtime overridden_by metadata.
"""

from typing import Any

from ..client import InfobloxClient
from ..models import CollectionResult
from ..storage import RawStore, page_records

RESERVATION_OBJECTS: dict[str, tuple[str, str, list[str]]] = {
    'fixedaddress': ('Fixed addresses and reservations', 'Fixed Reservations', [
        'ipv4addr', 'mac', 'dhcp_client_identifier', 'client_identifier_prepend_zero',
        'name', 'network', 'network_view', 'match_client',
        'agent_circuit_id', 'agent_remote_id', 'enable_ddns', 'ddns_hostname',
        'ddns_domainname', 'options', 'ms_options', 'ms_server',
        'cloud_info', 'comment', 'extattrs', 'disable',
        'is_invalid_mac', 'reserved_interface', 'logic_filter_rules', 'ignore_dhcp_option_list_request',
        'bootfile', 'bootserver', 'nextserver', 'deny_bootp',
        'enable_pxe_lease_time', 'pxe_lease_time',
    ]),
    'record:host': ('Fixed addresses and reservations', 'Host DHCP Context', [
        'name', 'network_view', 'disable', 'comment',
        'extattrs', 'ipv4addrs',
    ]),
    'record:host_ipv4addr': ('Fixed addresses and reservations', 'Host IPv4 DHCP', [
        'ipv4addr', 'mac', 'host', 'network',
        'network_view', 'configure_for_dhcp', 'match_client', 'options',
        'logic_filter_rules', 'is_invalid_mac', 'reserved_interface', 'ignore_client_requested_options',
        'bootfile', 'bootserver', 'nextserver', 'deny_bootp',
        'enable_pxe_lease_time', 'pxe_lease_time',
    ]),
    'roaminghost': ('Fixed addresses and reservations', 'Roaming Hosts', [
        'name', 'address_type', 'mac', 'dhcp_client_identifier',
        'client_identifier_prepend_zero', 'match_client', 'network_view', 'enable_ddns',
        'ddns_hostname', 'ddns_domainname', 'force_roaming_hostname', 'options',
        'comment', 'extattrs', 'disable', 'ignore_dhcp_option_list_request',
        'ipv6_duid', 'ipv6_mac_address', 'ipv6_match_option', 'ipv6_options',
        'preferred_lifetime', 'valid_lifetime', 'bootfile', 'bootserver',
        'nextserver', 'deny_bootp', 'enable_pxe_lease_time', 'pxe_lease_time',
    ]),
    'superhost': ('Fixed addresses and reservations', 'Superhost DHCP', [
        'name', 'comment', 'disabled', 'dhcp_associated_objects',
    ]),
    'superhostchild': ('Fixed addresses and reservations', 'Superhost Fixed Links', [
        'name', 'comment', 'data', 'disabled',
        'network_view', 'parent', 'record_parent', 'type',
        'associated_object',
    ]),
    'filtermac': ('DHCP filters and MAC filters', 'filtermac', [
        'name', 'comment', 'disable', 'default_mac_address_expiration',
        'enforce_expiration_times', 'never_expires', 'lease_time', 'options',
    ]),
    'macfilteraddress': ('DHCP filters and MAC filters', 'macfilteraddress', [
        'mac', 'filter', 'comment', 'authentication_time',
        'expiration_time', 'never_expires', 'fingerprint', 'is_registered_user',
    ]),
    'filteroption': ('DHCP filters and MAC filters', 'filteroption', [
        'name', 'comment', 'expression', 'apply_as_class',
        'option_space', 'option_list', 'lease_time', 'bootfile',
        'bootserver', 'next_server', 'pxe_lease_time',
    ]),
    'filterrelayagent': ('DHCP filters and MAC filters', 'filterrelayagent', [
        'name', 'comment', 'is_circuit_id', 'circuit_id_name',
        'is_circuit_id_substring', 'circuit_id_substring_offset', 'circuit_id_substring_length', 'is_remote_id',
        'remote_id_name', 'is_remote_id_substring', 'remote_id_substring_offset', 'remote_id_substring_length',
    ]),
    'filterfingerprint': ('DHCP filters and MAC filters', 'filterfingerprint', [
        'name', 'comment', 'fingerprint',
    ]),
    'filternac': ('DHCP filters and MAC filters', 'filternac', [
        'name', 'comment', 'expression', 'lease_time',
        'options',
    ]),
}

# A schema-verified search constraint keeps this projection limited to DHCP fixed addresses.
RESERVATION_FILTERS = {'superhostchild': {'type': 'FixedAddress'}}

# Known assessment relationships present in the schema but not readable in this LAB.
RESERVATION_RELATIONSHIP_FIELDS = {'fixedaddress': ('template',),
                                   'roaminghost': ('template', 'ipv6_template')}

RESERVATION_TYPES = {'fixedaddress', 'record:host', 'record:host_ipv4addr',
                     'roaminghost', 'superhost', 'superhostchild'}
FILTER_TYPES = set(RESERVATION_OBJECTS) - RESERVATION_TYPES


def collect_superhost_children(client: InfobloxClient, result: CollectionResult,
                               store: RawStore | None, selected_fields: list[str],
                               missing_fields: bool) -> None:
    """The LAB requires an exact parent name, in addition to the DHCP type filter.

    Keep one version-1 archive query and number its pages across parent searches.
    Optional subquery metadata records the actual parameters and page ownership.
    No response page is fabricated when the parent inventory is empty.
    """
    object_type = "superhostchild"
    area = RESERVATION_OBJECTS[object_type][0]
    parent_status = next((row.get("Collection Status") for row in result.coverage
                          if row.get("Object") == "superhost" and row.get("Query") == "raw"), None)
    incomplete = parent_status not in {"COMPLETE", "EMPTY"}
    names: list[str] = []
    for parent in result.records.get("superhost", []):
        name = parent.get("name")
        if not isinstance(name, str) or not name:
            incomplete = True
        elif name not in names:
            names.append(name)
    params = {"_return_fields": ",".join(selected_fields), "_paging": "1",
              "_return_as_object": "1", "_max_results": 1000, "type": "FixedAddress"}
    query = store.start_query(object_type, "raw", params) if store else None
    if query is not None:
        query.update(parent_object="superhost", parent_count=len(names), subqueries=[])
        store.save_manifest()
    captured: list[dict[str, Any]] = []
    failures = 0
    global_page = 0
    for name in names:
        subquery: dict[str, Any] = {"params": {**params, "parent": name}, "status": "PARTIAL",
                                    "pages": [], "record_count": 0}
        if query is not None:
            query["subqueries"].append(subquery)
            store.save_manifest()

        def save_page(_number: int, response: Any) -> None:
            nonlocal global_page
            global_page += 1
            if store and query is not None:
                store.save_page(query, global_page, response)
                subquery["pages"].append(query["pages"][-1])
            try:
                rows = page_records(response)
                captured.extend(rows)
                subquery["record_count"] += len(rows)
            except ValueError:
                pass  # The unchanged client validates after the original page is saved.
            if store:
                store.save_manifest()

        try:
            rows = client.get_all_objects(object_type, selected_fields,
                                          {"type": "FixedAddress", "parent": name},
                                          page_callback=save_page)
            subquery["status"] = "COMPLETE" if rows else "EMPTY"
        except Exception as exc:
            failures += 1
            subquery["status"] = "PARTIAL" if subquery["record_count"] else "ERROR"
            result.errors.append({"grid": result.grid, "area": area, "object_type": object_type,
                                  "query": "raw", "parent": name, "error": str(exc)})
        if store:
            store.save_manifest()
    if incomplete or missing_fields:
        status = "PARTIAL"
    elif failures:
        status = "PARTIAL" if captured else "ERROR"
    else:
        status = "COMPLETE" if captured else "EMPTY"
    notes = ["Read per observed superhost name with type=FixedAddress."]
    if incomplete:
        notes.append("Parent inventory is unavailable, incomplete or contains missing names; completeness is unknown.")
    elif not names:
        notes.append("Complete superhost inventory is empty; no child GET was executed and no response page was fabricated.")
    if missing_fields:
        notes.append("Some requested fields are unavailable; see schema coverage.")
    if failures:
        notes.append(f"{failures} parent searches failed; successfully captured pages remain available.")
    result.records[object_type] = captured
    result.coverage.append({"Grid": result.grid, "Area": area, "Object": object_type,
                            "Query": "raw", "Field": "", "Collection Status": status,
                            "Objects Found": len(captured), "Notes": " ".join(notes)})
    if store and query is not None:
        store.finish_query(query, status)

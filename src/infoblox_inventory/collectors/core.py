from __future__ import annotations

import logging
from typing import Any

from ..client import InfobloxClient
from ..models import ASSESSMENT_AREAS, CollectionResult
from ..schema import SchemaCache, index_fields, override_relationships
from ..storage import RawStore, page_records
from .topology import TOPOLOGY_OBJECTS


LOG = logging.getLogger(__name__)

# A bounded assessment field list; schema decides which fields and use flags exist.
DHCP_FIELDS = [
    "options", "nextserver", "bootfile", "bootserver", "pxe_lease_time", "authority",
    "deny_bootp", "lease_scavenge_time", "recycle_leases", "enable_ddns", "ddns_domainname",
    "ddns_generate_hostname", "ddns_ttl", "ddns_update_fixed_addresses", "ddns_use_option81",
    "update_dns_on_lease_renewal",
]

OBJECTS: dict[str, tuple[str, str, list[str]]] = {
    "networkview": ("Network Views", "Network Views", ["name", "comment", "extattrs"]),
    "grid:dhcpproperties": ("DHCP options and inheritance", "Grid DHCP", DHCP_FIELDS),
    "member:dhcpproperties": ("DHCP options and inheritance", "Member DHCP", ["name", "host_name", "enable_dhcp", *DHCP_FIELDS]),
    "network": ("Networks", "Networks", ["network", "network_view", "comment", "extattrs", "members", *DHCP_FIELDS]),
    "range": ("Ranges", "Ranges", ["start_addr", "end_addr", "network", "network_view", "name", "comment", "extattrs", "server_association_type", "member", "failover_association", *DHCP_FIELDS]),
    "fixedaddress": ("Fixed addresses and reservations", "Fixed Addresses", ["ipv4addr", "mac", "match_client", "network_view", "name", "comment", "extattrs", *DHCP_FIELDS]),
    "member": ("DHCP failover associations and/or Grid Members", "Members", ["name", "node_info", "host_name", "service_status"]),
    "filtermac": ("DHCP filters and MAC filters", "Filters", ["name", "pattern", "comment", "extattrs"]),
    "filteroption": ("DHCP filters and MAC filters", "Filters", ["name", "match", "comment", "extattrs"]),
    "extensibleattributedef": ("Extensible Attributes", "EA Definitions", ["name", "type", "flags", "list_values"]),
    **TOPOLOGY_OBJECTS,
}

INHERITANCE_OBJECTS = {"member:dhcpproperties", "network", "range", "fixedaddress"}
COLLECTOR_ALIASES = {
    "topology": set(TOPOLOGY_OBJECTS),
    "core": {"networkview", "grid:dhcpproperties", "member", "member:dhcpproperties", "network", "range"},
    "views": {"networkview"}, "network_views": {"networkview"}, "networks": {"network"},
    "ranges": {"range"}, "fixed_addresses": {"fixedaddress"}, "reservations": {"fixedaddress"},
    "members": {"member", "member:dhcpproperties"}, "failover": {"dhcpfailover"},
    "templates": {"networktemplate", "rangetemplate", "fixedaddresstemplate"},
    "options": {"grid:dhcpproperties", "member:dhcpproperties", "network", "range", "fixedaddress"},
    "filters": {"filtermac", "filteroption"}, "eas": {"extensibleattributedef"},
}


def _coverage(result: CollectionResult, area: str, object_type: str, query: str,
              status: str, count: int | str = "", note: str = "", field: str = "") -> None:
    result.coverage.append({"Grid": result.grid, "Area": area, "Object": object_type,
                            "Query": query, "Field": field, "Collection Status": status,
                            "Objects Found": count, "Notes": note})


def collect_grid(client: InfobloxClient, raw_dir: str | None = None, only: str | None = None) -> CollectionResult:
    selected = COLLECTOR_ALIASES.get(only, {only}) if only else set(OBJECTS)
    if not selected.issubset(OBJECTS):
        raise ValueError("Unknown collector; choose a documented alias or WAPI object")
    result = CollectionResult(client.grid.name, grid_url=client.grid.url,
                              wapi_version=client.wapi_version or "")
    store = RawStore(raw_dir, result) if raw_dir else None
    cache = SchemaCache(client)
    supported: set[str] | None = None
    try:
        root = cache.root()
        if store:
            store.save_schema(None, root)
        supported = cache.supported_objects
    except Exception as exc:
        result.fail("WAPI discovery", "root schema", exc)
    for object_type, (area, _label, requested) in OBJECTS.items():
        if object_type not in selected:
            continue
        if supported is not None and object_type not in supported:
            _coverage(result, area, object_type, "schema", "NOT_EXPOSED_BY_WAPI",
                      note="Object absent from root schema")
            continue
        try:
            schema = cache.object_schema(object_type)
            result.schemas[object_type] = schema
            if store:
                store.save_schema(object_type, schema)
            fields = index_fields(schema)
            readable = {name for name, metadata in fields.items()
                        if "supports" not in metadata or "r" in metadata["supports"]}
            relationships = override_relationships(schema)
            wanted = list(dict.fromkeys([*requested, *(relationships[name] for name in requested if name in relationships)]))
            selected_fields = [name for name in wanted if name in readable]
            missing = [name for name in wanted if name not in readable]
            for name in missing:
                _coverage(result, area, object_type, "schema", "NOT_EXPOSED_BY_WAPI",
                          note="Field absent or not readable in returned schema", field=name)
            if not selected_fields:
                _coverage(result, area, object_type, "raw", "PARTIAL", note="No requested readable fields; query skipped")
                continue
        except Exception as exc:
            result.fail(area, object_type, exc)
            continue
        modes = ["raw"]
        if object_type in INHERITANCE_OBJECTS:
            if any(name in relationships for name in selected_fields):
                modes.append("effective")
            else:
                _coverage(result, area, object_type, "effective", "PARTIAL",
                          note="Schema exposes no override metadata for selected fields; effective query not attempted")
        for mode in modes:
            filters = {"_inheritance": "True"} if mode == "effective" else None
            params = {"_return_fields": ",".join(selected_fields), "_paging": "1",
                      "_return_as_object": "1", "_max_results": 1000, **(filters or {})}
            query = store.start_query(object_type, mode, params) if store else None
            captured: list[dict[str, Any]] = []

            def save_page(number: int, response: Any) -> None:
                if store and query is not None:
                    store.save_page(query, number, response)
                try:
                    captured.extend(page_records(response))
                except ValueError:
                    pass  # Client validates after preserving the original response.

            target = result.records if mode == "raw" else result.effective_records
            try:
                rows = client.get_all_objects(object_type, selected_fields, filters, page_callback=save_page)
                target[object_type] = rows
                status = "PARTIAL" if missing else ("COMPLETE" if rows else "EMPTY")
                note = "Some requested fields are unavailable; see schema coverage rows" if missing else ""
                _coverage(result, area, object_type, mode, status, len(rows), note)
                if store and query is not None:
                    store.finish_query(query, "COMPLETE" if rows else "EMPTY")
            except Exception as exc:
                target[object_type] = captured
                status = "PARTIAL" if captured else "ERROR"
                _coverage(result, area, object_type, mode, status, len(captured), str(exc))
                result.errors.append({"grid": result.grid, "area": area, "object_type": object_type,
                                      "query": mode, "error": str(exc)})
                LOG.error("[%s] %s %s query failed: %s", result.grid, object_type, mode, exc)
                if store and query is not None:
                    store.finish_query(query, status)
    for area in ASSESSMENT_AREAS:
        if not any(item["Area"] == area for item in result.coverage):
            status = "MANUAL_REVIEW_REQUIRED" if area in {"Approval process", "Documentation requirements"} else "PARTIAL"
            _coverage(result, area, "", "", status,
                      note="Confirm with Grid owners" if status == "MANUAL_REVIEW_REQUIRED"
                      else "Assessment area is not fully covered by this increment")
    if store:
        store.finish_collection()
    return result

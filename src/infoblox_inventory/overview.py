"""Assessment landing-page rows derived from collected and normalized evidence."""
from __future__ import annotations

from collections import Counter
import json
from typing import Any

from .dataset import collection_time_utc
from .models import CollectionResult


OVERVIEW_HEADERS = ["Grid", "Section", "Metric", "Observed value", "Evidence / scope"]
_STATUSES = ("COMPLETE", "PARTIAL", "EMPTY", "NOT_CONFIGURED", "NOT_EXPOSED_BY_WAPI",
             "MANUAL_REVIEW_REQUIRED", "ERROR")
_INVENTORIES = (
    ("Networks", ("network",)),
    ("Ranges", ("range",)),
    ("Members", ("member",)),
    ("Fixed addresses / reservations", ("fixedaddress",)),
    ("Filter definitions", ("filtermac", "filteroption", "filterrelayagent", "filterfingerprint", "filternac")),
    ("MAC filter entries", ("macfilteraddress",)),
    ("Templates", ("networktemplate", "rangetemplate", "fixedaddresstemplate")),
    ("Option definitions", ("dhcpoptiondefinition",)),
)
_OPTION_LABELS = {
    51: "Lease time (DHCP option 51)",
    6: "DNS servers (DHCP option 6)",
    15: "Domain (DHCP option 15)",
    119: "Domain search (DHCP option 119)",
    3: "Router / gateway (DHCP option 3)",
    66: "TFTP server name (DHCP option 66)",
    67: "Bootfile name (DHCP option 67)",
}
_SCALAR_LABELS = {
    "nextserver": "Next server (nextserver)",
    "bootserver": "Boot server (bootserver)",
    "bootfile": "Bootfile (bootfile)",
    "pxe_lease_time": "PXE lease time (pxe_lease_time)",
    "enable_pxe_lease_time": "PXE lease setting (enable_pxe_lease_time)",
    "deny_bootp": "BOOTP setting (deny_bootp)",
    "enable_ddns": "DDNS setting (enable_ddns)",
    "ddns_domainname": "DDNS domain (ddns_domainname)",
}
_EFFECTIVE_OBJECTS = {"grid:dhcpproperties", "member:dhcpproperties", "network", "range", "fixedaddress"}
_REFERENCE_OBJECTS = ("dhcpoptiondefinition", "dhcpoptionspace", "extensibleattributedef")
_KPI_INVENTORIES = {"Networks", "Ranges", "Members", "Fixed addresses / reservations"}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _inventory(result: CollectionResult, object_types: tuple[str, ...],
               coverage: list[dict[str, Any]]) -> tuple[Any, str]:
    present = [name for name in object_types if name in result.records]
    absent = [name for name in object_types if name not in result.records]
    count = sum(len(result.records[name]) for name in present)
    statuses = []
    for name in object_types:
        observed = sorted({str(row.get("Collection Status")) for row in coverage
                           if row.get("Object") == name and not row.get("Field")
                           and row.get("Query") in {"raw", "schema"}})
        statuses.append(f"{name}: {', '.join(observed) or ('captured rows' if name in present else 'PARTIAL, not collected')}")
    notes = "; ".join(statuses)
    if absent:
        notes = "PARTIAL inventory scope; missing: " + ", ".join(absent) + ". " + notes
    if not present:
        known = {row.get("Collection Status") for row in coverage
                 if row.get("Object") in object_types and not row.get("Field")
                 and row.get("Query") in {"raw", "schema"}}
        state = next(iter(known)) if len(known) == 1 else "PARTIAL"
        if state not in {"ERROR", "NOT_EXPOSED_BY_WAPI", "NOT_CONFIGURED"}:
            state = "PARTIAL"
        return f"{state or 'PARTIAL'}; no captured inventory", notes
    incomplete = {row.get("Collection Status") for row in coverage
                  if row.get("Object") in object_types and not row.get("Field")
                  and row.get("Query") == "raw"} & {"ERROR", "PARTIAL"}
    if not count and incomplete:
        return f"{'ERROR' if 'ERROR' in incomplete else 'PARTIAL'}; 0 captured rows", notes
    return count, notes + ". Counts describe captured RAW rows; consult Coverage for completeness."


def _effective_summary(rows: list[dict[str, Any]]) -> tuple[str, str]:
    if not rows:
        return "PARTIAL; no effective evidence", "No normalized rows for this parameter; no RAW fallback."
    proven = [row for row in rows if row.get("status") == "COMPLETE"
              and row.get("multisource") is False and row.get("effective_value") is not None]
    values = Counter(_json(row["effective_value"]) for row in proven)
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    display = []
    for encoded, count in ordered[:4]:
        value = json.loads(encoded)
        text = value if isinstance(value, str) else encoded
        display.append(f"{text or '<empty string>'} ({count})")
    if len(ordered) > 4:
        display.append(f"+{len(ordered) - 4} more distinct values; see DHCP sheets")
    status_counts = Counter(str(row.get("status", "PARTIAL")) for row in rows)
    not_configured = status_counts["NOT_CONFIGURED"]
    multisource = sum(row.get("multisource") is True for row in rows)
    unresolved = len(rows) - len(proven) - not_configured
    if display:
        observed = "; ".join(display)
    elif not_configured == len(rows):
        observed = "NOT_CONFIGURED"
    else:
        observed = "PARTIAL; no confirmed effective value"
    if len(observed) > 350:
        observed = observed[:315] + "... [truncated; see DHCP sheets]"
    scopes = Counter(str(row.get("object_type", "")) for row in rows)
    note = (f"Observed values with row counts; confirmed={len(proven)}, "
            f"configured_here={sum(row.get('configured_here') is True for row in proven)}, "
            f"inherited={sum(row.get('inherited') is True for row in proven)}, "
            f"NOT_CONFIGURED={not_configured}, unresolved={unresolved}, multisource excluded={multisource}. "
            + "Statuses: " + ", ".join(f"{key}={count}" for key, count in sorted(status_counts.items()))
            + ". Scope: " + ", ".join(f"{key}={count}" for key, count in sorted(scopes.items()))
            + ". Configuration observations; no approved standard or service-activation claim.")
    return observed, note


def _collection_period(result: CollectionResult) -> tuple[Any, Any, Any, str]:
    source_rows = result.collection_sources
    timestamps = [row.get("Collected At") for row in source_rows] or [result.collected_at]
    parsed = [collection_time_utc(value) for value in timestamps]
    valid = [value for value in parsed if value is not None]
    invalid = len(parsed) - len(valid)
    prefix = "PARTIAL; observed " if invalid else ""
    earliest = prefix + min(valid).isoformat().replace("+00:00", "Z") if valid else "PARTIAL; unavailable"
    latest = prefix + max(valid).isoformat().replace("+00:00", "Z") if valid else "PARTIAL; unavailable"
    identifiers = {row["Archive ID"] for row in source_rows
                   if isinstance(row.get("Archive ID"), str) and row["Archive ID"]}
    unknown_ids = sum(not isinstance(row.get("Archive ID"), str) or not row["Archive ID"] for row in source_rows)
    archive_count = len(identifiers) if source_rows and not unknown_ids else f"PARTIAL; {len(identifiers)} identified archives"
    note = ("Timezone-aware source timestamps normalized to UTC; original values remain in Collection_Sources. "
            f"Unknown/invalid timestamp observations={invalid}. "
            "Archive count deduplicates original captures by Archive ID, not timestamp or object rows.")
    if not source_rows or unknown_ids:
        note += " PARTIAL archive identity: legacy or programmatic source evidence has no complete Archive ID mapping."
    return earliest, latest, archive_count, note


def overview_rows(results: list[CollectionResult], coverage: list[dict[str, Any]],
                  scalars: list[dict[str, Any]], options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize cumulative Grid inventories without resolving inheritance."""
    rows: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda item: item.grid):
        def add(section: str, metric: str, value: Any, evidence: str) -> None:
            rows.append(dict(zip(OVERVIEW_HEADERS, (result.grid, section, metric, value, evidence))))

        grid_coverage = [row for row in coverage if row.get("Grid") == result.grid]
        counts = Counter(str(row.get("Collection Status", "PARTIAL")) for row in grid_coverage)
        infrastructure = tuple(name for name in result.records if name not in _REFERENCE_OBJECTS)
        add("KPI", "Infrastructure / configuration rows",
            sum(len(result.records[name]) for name in infrastructure) if infrastructure else "PARTIAL; not collected",
            "Captured RAW rows excluding DHCP option definitions, DHCP option spaces and EA definitions. "
            "Related host objects may describe one endpoint; this is not an endpoint count. See Inventory and Coverage.")
        reference_count, reference_scope = _inventory(result, _REFERENCE_OBJECTS, grid_coverage)
        add("KPI", "Reference definition rows", reference_count, reference_scope)
        for metric, object_types in _INVENTORIES:
            if metric in _KPI_INVENTORIES:
                add("KPI", metric, *_inventory(result, object_types, grid_coverage))
        add("KPI", "Collection errors", len(result.errors), "Recorded collection errors; see Errors and Coverage.")
        add("KPI", "Manual-review observations", counts["MANUAL_REVIEW_REQUIRED"], "See Manual_Review; configuration does not establish organizational policy.")
        earliest, latest, archive_count, period_evidence = _collection_period(result)
        source_times = sorted({str(row.get("Collected At")) for row in result.collection_sources if row.get("Collected At")})
        if source_times:
            add("Collection", "Collection timestamps (UTC)", "; ".join(source_times),
                "Source collection timestamps; combined archives can represent different collection times. See Collection_Sources.")
        add("Collection", "Earliest collection (UTC)", earliest, period_evidence)
        add("Collection", "Latest collection (UTC)", latest, period_evidence)
        add("Collection", "Archive count", archive_count, period_evidence)
        add("Collection", "WAPI version", result.wapi_version or "PARTIAL; unavailable", "Version recorded in the collection archive.")
        add("Inventory", "Total captured object rows", sum(map(len, result.records.values())) if result.records else "PARTIAL; not collected",
            "Sum of RAW object rows across collected types; related host objects can describe the same endpoint. Uncollected types are excluded.")
        for metric, object_types in _INVENTORIES:
            if metric in _KPI_INVENTORIES:
                continue
            value, evidence = _inventory(result, object_types, grid_coverage)
            add("Reference definitions" if object_types[0] in _REFERENCE_OBJECTS else "Inventory", metric, value, evidence)
        for metric, object_type in (("Option spaces", "dhcpoptionspace"), ("EA definitions", "extensibleattributedef")):
            if object_type in result.records:
                add("Reference definitions", metric, *_inventory(result, (object_type,), grid_coverage))
        value, evidence = _inventory(result, ("record:host_ipv4addr",), grid_coverage)
        if "record:host_ipv4addr" in result.records:
            hosts = result.records["record:host_ipv4addr"]
            if hosts or isinstance(value, int):
                value = sum(row.get("configure_for_dhcp") is True for row in hosts)
            unknown = sum(type(row.get("configure_for_dhcp")) is not bool for row in hosts)
            evidence += f" Explicit configure_for_dhcp=true only; unresolved flags={unknown}. Parent activation and IPv6 are not assessed."
        add("Inventory", "Host IPv4 entries configured for DHCP", value, evidence)
        add("Coverage", "Coverage status", "; ".join(f"{key}={count}" for key, count in sorted(counts.items())) or "PARTIAL; no coverage evidence",
            "Counts of object/query/field observations, not percentages or an overall compliance verdict.")
        for status in _STATUSES:
            add("Coverage", status, counts[status], "Coverage observations with this exact status.")
        grid_options = [row for row in options if row.get("grid") == result.grid
                        and row.get("object_type") in _EFFECTIVE_OBJECTS and row.get("vendor_class") == "DHCP"]
        for number, label in _OPTION_LABELS.items():
            selected = [row for row in grid_options if str(row.get("option_number")) == str(number)]
            add("Effective DHCP", label, *_effective_summary(selected))
        grid_scalars = [row for row in scalars if row.get("grid") == result.grid
                        and row.get("object_type") in _EFFECTIVE_OBJECTS]
        scalar_labels = dict(_SCALAR_LABELS)
        for name in sorted({row.get("parameter") for row in grid_scalars if isinstance(row.get("parameter"), str)}):
            if name.startswith("ddns_") or name == "update_dns_on_lease_renewal":
                scalar_labels.setdefault(name, f"DDNS setting ({name})")
        for parameter, label in scalar_labels.items():
            selected = [row for row in grid_scalars if row.get("parameter") == parameter]
            add("Effective DHCP", label, *_effective_summary(selected))
    return rows

"""Assessment summaries preserve collection scope and authoritative inheritance evidence."""
from copy import deepcopy
import json
from pathlib import Path

from infoblox_inventory.models import CollectionResult
from infoblox_inventory.normalize import normalize_options, normalize_scalars
from infoblox_inventory.overview import OVERVIEW_HEADERS, overview_rows
from infoblox_inventory.storage import path_component


def _row(rows, metric, grid="LAB"):
    found = [row for row in rows if row["Grid"] == grid and row["Metric"] == metric]
    assert len(found) == 1
    return found[0]


def _coverage(obj, status, query="raw", field=""):
    return {"Grid": "LAB", "Object": obj, "Query": query, "Field": field,
            "Collection Status": status}


def _effective(parameter, value, **extra):
    return {"grid": "LAB", "object_type": "network", "parameter": parameter,
            "effective_value": value, "raw_value": "raw-must-not-leak", "status": "COMPLETE",
            "configured_here": False, "inherited": True, "multisource": False,
            "source_level": "Grid", **extra}


def _option(number, value, **extra):
    return {**_effective(number, value, option_number=number, vendor_class="DHCP"), **extra}


def test_missing_inventory_is_not_reported_as_empty_and_group_scope_is_explicit():
    result = CollectionResult("LAB", records={"network": [], "filtermac": [{"name": "Corporate"}]})
    coverage = [_coverage("network", "EMPTY"), _coverage("range", "ERROR"),
                _coverage("filtermac", "COMPLETE")]
    rows = overview_rows([result], coverage, [], [])
    assert _row(rows, "Networks")["Observed value"] == 0
    assert "EMPTY" in _row(rows, "Networks")["Evidence / scope"]
    assert _row(rows, "Ranges")["Observed value"].startswith("ERROR")
    assert _row(rows, "Members")["Observed value"].startswith("PARTIAL")
    filters = _row(rows, "Filter definitions")
    assert filters["Observed value"] == 1
    assert "PARTIAL inventory scope" in filters["Evidence / scope"]
    assert "filteroption" in filters["Evidence / scope"]
    assert "Corporate" not in json.dumps(rows)
    assert all(list(row) == OVERVIEW_HEADERS for row in rows)


def test_unexposed_object_status_and_field_unavailability_remain_distinct():
    result = CollectionResult("LAB", records={"network": [{}]})
    coverage = [_coverage("range", "NOT_EXPOSED_BY_WAPI", "schema"),
                _coverage("network", "COMPLETE"),
                _coverage("network", "NOT_EXPOSED_BY_WAPI", "schema", "optional_field")]
    rows = overview_rows([result], coverage, [], [])
    assert _row(rows, "Ranges")["Observed value"].startswith("NOT_EXPOSED_BY_WAPI")
    assert _row(rows, "Networks")["Observed value"] == 1
    assert "NOT_EXPOSED" not in _row(rows, "Networks")["Evidence / scope"]
    assert _row(rows, "NOT_EXPOSED_BY_WAPI")["Observed value"] == 2


def test_failed_zero_page_inventories_do_not_look_like_successfully_empty_results():
    result = CollectionResult("LAB", records={"network": [], "record:host_ipv4addr": []})
    coverage = [_coverage("network", "ERROR"), _coverage("record:host_ipv4addr", "PARTIAL")]
    rows = overview_rows([result], coverage, [], [])
    assert _row(rows, "Networks")["Observed value"] == "ERROR; 0 captured rows"
    assert _row(rows, "Host IPv4 entries configured for DHCP")["Observed value"] == "PARTIAL; 0 captured rows"


def test_counts_separate_filter_entries_templates_and_explicit_host_dhcp_flags():
    records = {name: [{}] for name in ("network", "range", "member", "fixedaddress",
               "filtermac", "filteroption", "filterrelayagent", "filterfingerprint", "filternac",
               "networktemplate", "rangetemplate", "fixedaddresstemplate", "dhcpoptiondefinition")}
    records["macfilteraddress"] = [{}, {}, {}]
    records["record:host_ipv4addr"] = [{"configure_for_dhcp": value} for value in (True, False, 1, "true", None)]
    records["record:host"] = [{"ipv4addrs": [{"configure_for_dhcp": True}]}]
    result = CollectionResult("LAB", records=records, errors=[{"error": "sanitized error"}])
    coverage = [_coverage(name, "COMPLETE") for name in records]
    coverage.append(_coverage("", "MANUAL_REVIEW_REQUIRED"))
    before = deepcopy((result, coverage))
    rows = overview_rows([result], coverage, [], [])
    assert _row(rows, "Total captured object rows")["Observed value"] == sum(map(len, records.values()))
    assert _row(rows, "Filter definitions")["Observed value"] == 5
    assert _row(rows, "MAC filter entries")["Observed value"] == 3
    assert _row(rows, "Templates")["Observed value"] == 3
    assert _row(rows, "Host IPv4 entries configured for DHCP")["Observed value"] == 1
    assert "unresolved flags=3" in _row(rows, "Host IPv4 entries configured for DHCP")["Evidence / scope"]
    assert _row(rows, "Collection errors")["Observed value"] == 1
    assert _row(rows, "Manual-review observations")["Observed value"] == 1
    assert (result, coverage) == before


def test_source_timestamps_are_explicit_without_inventing_one_snapshot_time():
    result = CollectionResult("LAB", wapi_version="2.13.7", collected_at="combined label",
                              collection_sources=[{"Collected At": "2026-09-20T13:00:00Z"},
                                                  {"Collected At": "2026-09-20T12:00:00Z"},
                                                  {"Collected At": "2026-09-20T12:00:00Z"}])
    rows = overview_rows([result], [], [], [])
    assert _row(rows, "Collection timestamps (UTC)")["Observed value"] == "2026-09-20T12:00:00Z; 2026-09-20T13:00:00Z"
    assert _row(rows, "WAPI version")["Observed value"] == "2.13.7"
    assert _row(rows, "Coverage status")["Observed value"].startswith("PARTIAL")


def test_effective_lease_summary_uses_confirmed_values_and_counts_unresolved_members():
    options = [_option(51, "28800"), _option(51, "3600", object_type="range", configured_here=True, inherited=False),
               _option(51, None, object_type="member:dhcpproperties", status="PARTIAL", raw_value="43200"),
               _option(51, "must-not-leak", multisource=True)]
    rows = overview_rows([CollectionResult("LAB")], [], [], options)
    lease = _row(rows, "Lease time (DHCP option 51)")
    assert lease["Observed value"] == "28800 (1); 3600 (1)"
    assert "configured_here=1, inherited=1" in lease["Evidence / scope"]
    assert "unresolved=2, multisource excluded=1" in lease["Evidence / scope"]
    assert "43200" not in json.dumps(rows)
    assert "must-not-leak" not in json.dumps(rows)


def test_not_configured_missing_and_multisource_evidence_are_not_collapsed():
    options = [_option(6, None, status="NOT_CONFIGURED", source_level="NOT_DEFINED"),
               _option(3, ["192.0.2.1"], multisource=True)]
    rows = overview_rows([CollectionResult("LAB")], [], [], options)
    assert _row(rows, "DNS servers (DHCP option 6)")["Observed value"] == "NOT_CONFIGURED"
    assert _row(rows, "Domain (DHCP option 15)")["Observed value"] == "PARTIAL; no effective evidence"
    assert _row(rows, "Router / gateway (DHCP option 3)")["Observed value"] == "PARTIAL; no confirmed effective value"
    assert "multisource excluded=1" in _row(rows, "Router / gateway (DHCP option 3)")["Evidence / scope"]


def test_dhcp_option_codes_do_not_mix_vendor_values_domain_search_or_pxe_lease():
    options = [_option(51, "28800", parameter="misleading-name"),
               _option(15, "example.test"), _option(119, "search.example.test"),
               _option(15, "vendor-domain", vendor_class="Vendor"),
               _option(51, "vendor-lease", vendor_class="Vendor")]
    scalars = [_effective("pxe_lease_time", 120)]
    rows = overview_rows([CollectionResult("LAB")], [], scalars, options)
    assert _row(rows, "Lease time (DHCP option 51)")["Observed value"] == "28800 (1)"
    assert _row(rows, "PXE lease time (pxe_lease_time)")["Observed value"] == "120 (1)"
    assert _row(rows, "Domain (DHCP option 15)")["Observed value"] == "example.test (1)"
    assert _row(rows, "Domain search (DHCP option 119)")["Observed value"] == "search.example.test (1)"
    assert "vendor-domain" not in json.dumps(rows) and "vendor-lease" not in json.dumps(rows)


def test_effective_observations_are_bounded_and_deterministic_with_value_counts():
    options = [_option(6, f"192.0.2.{number}") for number in range(1, 7)]
    options.append(_option(6, "192.0.2.6"))
    result = CollectionResult("LAB")
    rows = overview_rows([result], [], [], options)
    assert rows == overview_rows([result], [], [], list(reversed(options)))
    observed = _row(rows, "DNS servers (DHCP option 6)")["Observed value"]
    assert observed.startswith("192.0.2.6 (2)")
    assert "+2 more distinct values" in observed
    assert "192.0.2.5" not in observed


def test_long_observed_text_is_bounded_without_changing_normalized_evidence():
    options = [_option(119, "long.example.test," * 100)]
    before = deepcopy(options)
    rows = overview_rows([CollectionResult("LAB")], [], [], options)
    observed = _row(rows, "Domain search (DHCP option 119)")["Observed value"]
    assert len(observed) <= 350
    assert observed.endswith("[truncated; see DHCP sheets]")
    assert options == before


def test_false_zero_empty_string_and_nested_values_remain_observed_values():
    scalars = [_effective("enable_ddns", False), _effective("pxe_lease_time", 0),
               _effective("bootfile", ""), _effective("nextserver", None)]
    options = [_option(119, ["first.example", "second.example"])]
    rows = overview_rows([CollectionResult("LAB")], [], scalars, options)
    assert _row(rows, "DDNS setting (enable_ddns)")["Observed value"] == "false (1)"
    assert _row(rows, "PXE lease time (pxe_lease_time)")["Observed value"] == "0 (1)"
    assert _row(rows, "Bootfile (bootfile)")["Observed value"] == "<empty string> (1)"
    assert _row(rows, "Next server (nextserver)")["Observed value"].startswith("PARTIAL")
    assert '["first.example", "second.example"]' in _row(rows, "Domain search (DHCP option 119)")["Observed value"]


def test_template_filter_and_unrelated_grid_rows_cannot_supply_effective_values():
    scalars = [_effective("ddns_ttl", 300), _effective("ddns_ttl", 900, grid="OTHER"),
               _effective("bootfile", "template-only", object_type="networktemplate")]
    options = [_option(51, "filter-only", object_type="filtermac")]
    results = [CollectionResult("LAB"), CollectionResult("OTHER")]
    rows = overview_rows(results, [], scalars, options)
    assert _row(rows, "DDNS setting (ddns_ttl)")["Observed value"] == "300 (1)"
    assert _row(rows, "DDNS setting (ddns_ttl)", "OTHER")["Observed value"] == "900 (1)"
    assert "template-only" not in json.dumps(rows) and "filter-only" not in json.dumps(rows)


def test_real_lab_overview_preserves_network_shadow_lease_and_member_limitation():
    capture = Path(__file__).parent / "fixtures" / "live_lab_20260920"
    provenance = json.loads((capture / "provenance.json").read_text(encoding="utf-8"))
    result = CollectionResult("LAB", wapi_version=provenance["wapi_version"], collected_at=provenance["collected_at"])
    for name in ("networkview", "grid:dhcpproperties", "member", "member:dhcpproperties", "network", "range"):
        for mode, target in (("raw", result.records), ("effective", result.effective_records)):
            path = capture / path_component(name) / mode / "page-000001.json"
            if path.exists():
                target[name] = json.loads(path.read_text(encoding="utf-8"))["result"]
        path = capture / "schema" / (path_component(name) + ".json")
        if path.exists():
            result.schemas[name] = json.loads(path.read_text(encoding="utf-8"))
    arguments = (result.grid, result.grid_url, result.wapi_version, result.records, result.effective_records, result.schemas)
    rows = overview_rows([result], [], normalize_scalars(*arguments), normalize_options(*arguments))
    lease = _row(rows, "Lease time (DHCP option 51)")
    assert "28800 (2)" in lease["Observed value"] and "3600 (1)" in lease["Observed value"]
    assert "43200" not in lease["Observed value"]
    assert "unresolved=1" in lease["Evidence / scope"]
    assert "member:dhcpproperties=1" in lease["Evidence / scope"]

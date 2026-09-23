"""Deterministic usefulness and fingerprint discovery regressions."""
from copy import deepcopy

from infoblox_inventory.models import CollectionResult
from infoblox_inventory.profile_discovery import (
    build_profile_discovery, build_profile_fingerprints, build_profile_usefulness,
    derive_gateway_convention,
)


def _coverage(kind, count, query="effective"):
    return {
        "Grid": "LAB", "Object": kind, "Query": query, "Field": "",
        "Collection Status": "COMPLETE", "Objects Found": count,
    }


def _option(kind, index, number, value, name):
    return {
        "grid": "LAB", "object_type": kind, "object_ref": f"{kind}/LAB/{index}",
        "object_name": f"{kind}-{index}", "network_view": "default",
        "parent_network": f"10.0.{index}.0/24" if kind == "network" else "10.10.0.0/24",
        "parameter": name, "option_number": number, "vendor_class": "DHCP",
        "effective_value": value, "configured_here": False, "inherited": True,
        "multisource": False, "source_level": "Grid", "source_object": "LAB",
        "source_ref": "grid:dhcpproperties/LAB", "status": "COMPLETE",
    }


def _scalar(kind, index, parameter, value):
    return {
        "grid": "LAB", "object_type": kind, "object_ref": f"{kind}/LAB/{index}",
        "object_name": f"{kind}-{index}", "network_view": "default",
        "parent_network": f"10.0.{index}.0/24" if kind == "network" else "10.10.0.0/24",
        "parameter": parameter, "effective_value": value,
        "configured_here": False, "inherited": True, "multisource": False,
        "source_level": "Grid", "source_object": "LAB",
        "source_ref": "grid:dhcpproperties/LAB", "status": "COMPLETE",
    }


def _core_options(kind, index, *, lease="3600", dns="192.0.2.53", domain="lab.example",
                  router=None):
    if router is None:
        router = f"10.0.{index}.3" if kind == "network" else "10.10.0.3"
    return [
        _option(kind, index, 51, lease, "dhcp-lease-time"),
        _option(kind, index, 6, dns, "domain-name-servers"),
        _option(kind, index, 15, domain, "domain-name"),
        _option(kind, index, 3, router, "routers"),
    ]


def _network_result():
    networks = [
        {"_ref": f"network/LAB/{i}", "network": f"10.0.{i}.0/24", "network_view": "default",
         "members": [{"_struct": "dhcpmember", "name": "m1"}]}
        for i in range(3)
    ]
    return CollectionResult(
        grid="LAB",
        records={"network": networks, "range": []},
        effective_records={"network": deepcopy(networks), "range": []},
        coverage=[_coverage("network", 3, query) for query in ("raw", "effective")]
                 + [_coverage("range", 0, query) for query in ("raw", "effective")],
    )


def test_gateway_derivation_preserves_repeated_host_offsets_and_special_states():
    assert derive_gateway_convention({"status": "VALUE", "value": "10.0.0.3"}, "10.0.0.0/24") == {
        "status": "VALUE", "value": "HOST_OFFSET_3"
    }
    assert derive_gateway_convention({"status": "VALUE", "value": "10.0.0.1"}, "10.0.0.0/24")["value"] == "FIRST_USABLE"
    assert derive_gateway_convention({"status": "VALUE", "value": "10.0.0.254"}, "10.0.0.0/24")["value"] == "LAST_USABLE"
    assert derive_gateway_convention({"status": "VALUE", "value": ""}, "10.0.0.0/24")["value"] == "EMPTY_VALUE"
    assert derive_gateway_convention({"status": "VALUE", "value": "10.0.0.1,10.0.0.2"}, "10.0.0.0/24")["value"] == "MULTIPLE_ROUTERS"
    assert derive_gateway_convention({"status": "NOT_CONFIGURED", "value": None}, "10.0.0.0/24")["status"] == "NOT_CONFIGURED"
    assert derive_gateway_convention({"status": "UNRESOLVED", "value": None}, "10.0.0.0/24")["status"] == "UNRESOLVED"


def test_network_exact_core_fingerprints_are_stable_and_not_prevalence_ids():
    result = _network_result()
    options = []
    options += _core_options("network", 0)
    options += _core_options("network", 1)
    options += _core_options("network", 2, domain="other.example", router="10.0.2.1")

    fingerprints, assignments, kpis = build_profile_fingerprints([result], [], options)
    network_fps = [row for row in fingerprints if row["Profile"] == "Network Profile v1"]
    assert [row["Object Count"] for row in network_fps] == [2, 1]
    assert network_fps[0]["Share of Profiled %"] == 66.7
    assert network_fps[0]["Fingerprint ID"].startswith("NET-FP1-")
    assert network_fps[0]["Gateway Convention"] == "HOST_OFFSET_3"
    assert len(network_fps[0]["Full SHA256"]) == 64

    network_assignments = [row for row in assignments if row["Scope"] == "Network"]
    assert all(row["Population Status"] == "PROFILED" for row in network_assignments)
    assert len({row["Fingerprint ID"] for row in network_assignments}) == 2

    network_kpi = next(row for row in kpis if row["Profile"] == "Network Profile v1")
    assert network_kpi["Applicable Objects"] == 3
    assert network_kpi["Profiled Objects"] == 3
    assert network_kpi["Distinct Profiles"] == 2
    assert network_kpi["Top-1 Share of Profiled %"] == 66.7

    reversed_fps, reversed_assignments, _ = build_profile_fingerprints(
        [result], [], list(reversed(options))
    )
    assert {
        (row["Object Ref"], row["Fingerprint ID"])
        for row in network_assignments
    } == {
        (row["Object Ref"], row["Fingerprint ID"])
        for row in reversed_assignments if row["Scope"] == "Network"
    }
    assert {row["Fingerprint ID"] for row in network_fps} == {
        row["Fingerprint ID"] for row in reversed_fps if row["Profile"] == "Network Profile v1"
    }


def test_feature_overlay_difference_does_not_split_core_profile():
    result = _network_result()
    result.records["network"] = result.records["network"][:2]
    result.effective_records["network"] = result.effective_records["network"][:2]
    result.coverage = [_coverage("network", 2, query) for query in ("raw", "effective")]
    options = _core_options("network", 0) + _core_options("network", 1)
    scalars = [
        _scalar("network", 0, "enable_ddns", True),
        _scalar("network", 1, "enable_ddns", False),
    ]
    fingerprints, assignments, _kpis = build_profile_fingerprints([result], scalars, options)
    network_fps = [row for row in fingerprints if row["Profile"] == "Network Profile v1"]
    assert len(network_fps) == 1
    assert network_fps[0]["Object Count"] == 2
    ids = {row["Fingerprint ID"] for row in assignments if row["Scope"] == "Network"}
    assert len(ids) == 1
    assert '"ddns_enabled"' in network_fps[0]["Feature Overlay Distributions"]


def test_empty_core_value_is_visible_but_kept_literal_in_canonical_payload():
    result = _network_result()
    result.records["network"] = result.records["network"][:1]
    result.effective_records["network"] = result.effective_records["network"][:1]
    result.coverage = [_coverage("network", 1, query) for query in ("raw", "effective")]
    options = _core_options("network", 0, dns="")
    fingerprints, assignments, _kpis = build_profile_fingerprints([result], [], options)
    network_fp = next(row for row in fingerprints if row["Profile"] == "Network Profile v1")
    assert network_fp["DNS Servers"] == "EMPTY_VALUE"
    assert '"dns_servers":{"status":"VALUE","value":""}' in network_fp["Canonical Payload"]
    assignment = next(row for row in assignments if row["Scope"] == "Network")
    assert assignment["DNS Servers"] == "EMPTY_VALUE"


def test_range_association_family_is_part_of_fingerprint_and_none_is_not_applicable():
    ranges = [
        {"_ref": "range/LAB/0", "start_addr": "10.10.0.10", "end_addr": "10.10.0.20",
         "network": "10.10.0.0/24", "network_view": "default", "server_association_type": "MS_SERVER"},
        {"_ref": "range/LAB/1", "start_addr": "10.10.0.30", "end_addr": "10.10.0.40",
         "network": "10.10.0.0/24", "network_view": "default", "server_association_type": "MS_SERVER"},
        {"_ref": "range/LAB/2", "start_addr": "10.10.0.50", "end_addr": "10.10.0.60",
         "network": "10.10.0.0/24", "network_view": "default", "server_association_type": "MEMBER"},
        {"_ref": "range/LAB/3", "start_addr": "10.10.0.70", "end_addr": "10.10.0.80",
         "network": "10.10.0.0/24", "network_view": "default", "server_association_type": "NONE"},
    ]
    result = CollectionResult(
        grid="LAB",
        records={"network": [], "range": ranges},
        effective_records={"network": [], "range": deepcopy(ranges)},
        coverage=[_coverage("range", 4, query) for query in ("raw", "effective")]
                 + [_coverage("network", 0, query) for query in ("raw", "effective")],
    )
    options = []
    for i in range(3):
        options += _core_options("range", i)

    fingerprints, assignments, kpis = build_profile_fingerprints([result], [], options)
    range_fps = [row for row in fingerprints if row["Profile"] == "Range Profile v1"]
    assert [(row["Association Family"], row["Object Count"]) for row in range_fps] == [
        ("MS_SERVER", 2), ("MEMBER", 1)
    ]
    range_assignments = [row for row in assignments if row["Scope"] == "Range"]
    none = next(row for row in range_assignments if row["Association Family"] == "NONE")
    assert none["Population Status"] == "NOT_APPLICABLE_TO_DHCP_PROFILE"
    assert none["Fingerprint ID"] == ""
    range_kpi = next(row for row in kpis if row["Profile"] == "Range Profile v1")
    assert range_kpi["Applicable Objects"] == 3
    assert range_kpi["Profiled Objects"] == 3
    assert range_kpi["Distinct Profiles"] == 2


def test_unresolved_core_input_blocks_normal_fingerprint():
    result = _network_result()
    result.records["network"] = result.records["network"][:1]
    result.effective_records["network"] = [{**result.effective_records["network"][0], "options": []}]
    result.coverage = [_coverage("network", 1, query) for query in ("raw", "effective")]
    options = [
        _option("network", 0, 51, "3600", "dhcp-lease-time"),
        _option("network", 0, 15, "lab.example", "domain-name"),
        _option("network", 0, 3, "10.0.0.3", "routers"),
    ]
    fingerprints, assignments, kpis = build_profile_fingerprints([result], [], options)
    assert not [row for row in fingerprints if row["Profile"] == "Network Profile v1"]
    row = next(row for row in assignments if row["Scope"] == "Network")
    assert row["Population Status"] == "UNRESOLVED_PROFILE_INPUTS"
    assert "dhcp.dns_servers.network" in row["Missing Core Inputs"]
    network_kpi = next(row for row in kpis if row["Profile"] == "Network Profile v1")
    assert network_kpi["Profiled Objects"] == 0
    assert network_kpi["Unresolved Profile Objects"] == 1


def test_usefulness_reports_variability_without_quality_score():
    result = _network_result()
    options = []
    options += _core_options("network", 0)
    options += _core_options("network", 1)
    options += _core_options("network", 2, domain="other.example", router="10.0.2.1")
    rows = build_profile_usefulness([result], [], options, [])
    lease = next(row for row in rows if row["Parameter ID"] == "dhcp.lease_time.network")
    domain = next(row for row in rows if row["Parameter ID"] == "dhcp.domain_name.network")
    gateway = next(row for row in rows if row["Parameter ID"] == "dhcp.router.network")
    assert lease["Resolved Objects"] == 3
    assert lease["Distinct Resolved States"] == 1
    assert lease["Invariant Among Resolved"] is True
    assert domain["Distinct Configured Values"] == 2
    assert domain["Invariant Among Resolved"] is False
    assert gateway["Fingerprint Role"] == "DERIVED_CORE"
    assert gateway["Distinct Configured Values"] == 2
    assert "Score" not in lease


def test_combined_discovery_returns_all_four_report_sections():
    result = _network_result()
    options = sum((_core_options("network", i) for i in range(3)), [])
    usefulness, fingerprints, assignments, kpis = build_profile_discovery(
        [result], [], options, []
    )
    assert usefulness
    assert fingerprints
    assert assignments
    assert len(kpis) == 2

"""Regression tests for deterministic Profile Dimensions v1."""
from copy import deepcopy

from infoblox_inventory.models import CollectionResult
from infoblox_inventory.profile_dimensions import build_profile_dimensions


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


def _network_result(count=2):
    networks = [
        {
            "_ref": f"network/LAB/{i}", "network": f"10.0.{i}.0/24",
            "network_view": "default", "members": [{"_struct": "dhcpmember", "name": "m1"}],
        }
        for i in range(count)
    ]
    return CollectionResult(
        grid="LAB",
        records={"network": networks, "range": []},
        effective_records={"network": deepcopy(networks), "range": []},
        coverage=[_coverage("network", count, query) for query in ("raw", "effective")]
                 + [_coverage("range", 0, query) for query in ("raw", "effective")],
    )


def _network_evidence(index, *, ddns_enabled=True):
    options = [
        _option("network", index, 51, "3600", "dhcp-lease-time"),
        _option("network", index, 6, "192.0.2.53,192.0.2.54", "domain-name-servers"),
        _option("network", index, 15, "lab.example", "domain-name"),
        _option("network", index, 3, f"10.0.{index}.3", "routers"),
        _option("network", index, 119, "lab.example", "domain-search"),
        _option("network", index, 42, "192.0.2.42", "ntp-servers"),
        _option("network", index, 66, "192.0.2.66", "tftp-server-name"),
        _option("network", index, 67, "boot\\x64\\wdsmgfw.efi", "bootfile-name"),
    ]
    scalars = [
        _scalar("network", index, "enable_ddns", ddns_enabled),
        _scalar("network", index, "ddns_domainname", "lab.example"),
        _scalar("network", index, "ddns_generate_hostname", False),
        _scalar("network", index, "ddns_ttl", 3600),
        _scalar("network", index, "ddns_update_fixed_addresses", True),
        _scalar("network", index, "ddns_use_option81", True),
        _scalar("network", index, "update_dns_on_lease_renewal", True),
        _scalar("network", index, "nextserver", "192.0.2.10"),
        _scalar("network", index, "bootserver", "wds.lab.example"),
        _scalar("network", index, "bootfile", "boot\\x64\\wdsmgfw.efi"),
        _scalar("network", index, "pxe_lease_time", 3600),
        _scalar("network", index, "deny_bootp", False),
    ]
    return scalars, options


def test_ddns_difference_splits_dns_dimension_but_not_dhcp_core():
    result = _network_result(2)
    scalars = []
    options = []
    for index, enabled in ((0, True), (1, False)):
        item_scalars, item_options = _network_evidence(index, ddns_enabled=enabled)
        scalars.extend(item_scalars)
        options.extend(item_options)

    fingerprints, assignments, kpis, compositions = build_profile_dimensions(
        [result], scalars, options
    )

    core = [row for row in fingerprints if row["Scope"] == "Network"
            and row["Dimension"] == "DHCP Core"]
    dns = [row for row in fingerprints if row["Scope"] == "Network"
           and row["Dimension"] == "DNS/DDNS"]
    assert len(core) == 1
    assert core[0]["Object Count"] == 2
    assert core[0]["Dimension Fingerprint ID"].startswith("NET-CORE1-")
    assert len(dns) == 2
    assert all(row["Dimension Fingerprint ID"].startswith("NET-DNS1-") for row in dns)

    dns_assignments = [row for row in assignments if row["Scope"] == "Network"
                       and row["Dimension"] == "DNS/DDNS"]
    assert len({row["Dimension Fingerprint ID"] for row in dns_assignments}) == 2
    assert all(row["Population Status"] == "PROFILED" for row in dns_assignments)

    dns_kpi = next(row for row in kpis if row["Scope"] == "Network"
                   and row["Dimension"] == "DNS/DDNS")
    assert dns_kpi["Applicable Objects"] == 2
    assert dns_kpi["Profiled Objects"] == 2
    assert dns_kpi["Distinct Fingerprints"] == 2
    assert all(row["Composition Status"] == "COMPLETE" for row in compositions)


def test_deferred_pxe_lease_enabled_does_not_block_pxe_dimension_identity():
    result = _network_result(1)
    scalars, options = _network_evidence(0)

    fingerprints, assignments, _kpis, compositions = build_profile_dimensions(
        [result], scalars, options
    )

    pxe = next(row for row in fingerprints if row["Scope"] == "Network"
               and row["Dimension"] == "PXE")
    assert pxe["Dimension Fingerprint ID"].startswith("NET-PXE1-")
    assert "pxe.lease_enabled.network" in pxe["Deferred Inputs"]
    assert "pxe_lease_enabled" not in pxe["Canonical Payload"]

    assignment = next(row for row in assignments if row["Scope"] == "Network"
                      and row["Dimension"] == "PXE")
    assert assignment["Population Status"] == "PROFILED"
    assert assignment["Missing Inputs"] == ""
    assert "pxe.lease_enabled.network" in assignment["Deferred Inputs"]
    assert compositions[0]["PXE"] == pxe["Dimension Fingerprint ID"]


def test_range_association_dimension_preserves_none_and_rejects_unknown():
    ranges = [
        {
            "_ref": "range/LAB/0", "start_addr": "10.10.0.10", "end_addr": "10.10.0.20",
            "network": "10.10.0.0/24", "network_view": "default",
            "server_association_type": "MS_SERVER",
        },
        {
            "_ref": "range/LAB/1", "start_addr": "10.10.0.30", "end_addr": "10.10.0.40",
            "network": "10.10.0.0/24", "network_view": "default",
            "server_association_type": "NONE",
        },
        {
            "_ref": "range/LAB/2", "start_addr": "10.10.0.50", "end_addr": "10.10.0.60",
            "network": "10.10.0.0/24", "network_view": "default",
            "server_association_type": "VENDOR_FUTURE",
        },
    ]
    result = CollectionResult(
        grid="LAB",
        records={"network": [], "range": ranges},
        effective_records={"network": [], "range": deepcopy(ranges)},
        coverage=[_coverage("range", 3, query) for query in ("raw", "effective")]
                 + [_coverage("network", 0, query) for query in ("raw", "effective")],
    )

    fingerprints, assignments, kpis, compositions = build_profile_dimensions(
        [result], [], []
    )
    assoc = [row for row in fingerprints if row["Dimension"] == "Association"]
    assert len(assoc) == 2
    assert all(row["Dimension Fingerprint ID"].startswith("RNG-ASSOC1-") for row in assoc)
    assert {row["Dimension Values"] for row in assoc} == {
        '{"association_family":"MS_SERVER"}',
        '{"association_family":"NONE"}',
    }

    assoc_assignments = [row for row in assignments if row["Dimension"] == "Association"]
    none = next(row for row in assoc_assignments if row["Association Family"] == "NONE")
    unknown = next(row for row in assoc_assignments if row["Association Family"] == "OTHER")
    assert none["Population Status"] == "PROFILED"
    assert unknown["Population Status"] == "UNRESOLVED_ASSOCIATION"
    assert unknown["Dimension Fingerprint ID"] == ""

    assoc_kpi = next(row for row in kpis if row["Dimension"] == "Association")
    assert assoc_kpi["Applicable Objects"] == 3
    assert assoc_kpi["Profiled Objects"] == 2
    assert assoc_kpi["Unresolved Dimension Objects"] == 1

    none_composition = next(row for row in compositions if row["Association Family"] == "NONE")
    unknown_composition = next(row for row in compositions if row["Association Family"] == "OTHER")
    assert none_composition["Composition Status"] == "NOT_APPLICABLE_TO_DHCP_PROFILE"
    assert unknown_composition["Composition Status"] == "UNRESOLVED_ASSOCIATION"


def test_dimension_ids_and_compositions_are_deterministic_when_evidence_order_changes():
    result = _network_result(2)
    scalars = []
    options = []
    for index in range(2):
        item_scalars, item_options = _network_evidence(index)
        scalars.extend(item_scalars)
        options.extend(item_options)

    first = build_profile_dimensions([result], scalars, options)
    second = build_profile_dimensions([result], list(reversed(scalars)), list(reversed(options)))

    first_ids = {
        (row["Scope"], row["Dimension"], row["Canonical Payload"], row["Dimension Fingerprint ID"])
        for row in first[0]
    }
    second_ids = {
        (row["Scope"], row["Dimension"], row["Canonical Payload"], row["Dimension Fingerprint ID"])
        for row in second[0]
    }
    assert first_ids == second_ids
    assert first[3] == second[3]

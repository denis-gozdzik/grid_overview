"""Deterministic profile usefulness and fingerprint regression tests."""

from copy import deepcopy

import pytest

from infoblox_inventory.models import CollectionResult
from infoblox_inventory.profile_fingerprint import (
    PROFILE_DISCOVERY_HEADERS,
    PROFILE_HEADERS,
    PROFILE_OBJECT_HEADERS,
    PROFILE_USEFULNESS_HEADERS,
    _gateway_convention,
    build_profile_discovery,
    build_profile_usefulness,
)


def _option(kind, ref, num, value, *, status="COMPLETE", source_level="Grid",
            configured_here=False, inherited=True, multisource=False):
    return {
        "grid": "LAB",
        "object_type": kind,
        "object_ref": ref,
        "object_name": ref,
        "network_view": "default",
        "parent_network": "",
        "parameter": {51: "dhcp-lease-time", 6: "domain-name-servers",
                      15: "domain-name", 3: "routers"}.get(num, f"option-{num}"),
        "option_number": num,
        "vendor_class": "DHCP",
        "effective_value": value,
        "configured_here": configured_here,
        "inherited": inherited,
        "multisource": multisource,
        "source_level": source_level,
        "source_object": "LAB",
        "source_ref": "grid:dhcpproperties/LAB",
        "status": status,
    }


def _network(index, cidr):
    return {
        "_ref": f"network/LAB/{index}",
        "network": cidr,
        "network_view": "default",
        "members": ["m1"],
    }


def _range(index, network, association):
    return {
        "_ref": f"range/LAB/{index}",
        "start_addr": str(network).replace(".0/24", ".10"),
        "end_addr": str(network).replace(".0/24", ".20"),
        "network": network,
        "network_view": "default",
        "server_association_type": association,
    }


def _result():
    networks = [
        _network(0, "10.0.0.0/24"),
        _network(1, "10.0.1.0/24"),
        _network(2, "10.0.2.0/24"),
    ]
    ranges = [
        _range(0, "10.10.0.0/24", "MS_SERVER"),
        _range(1, "10.10.1.0/24", "MS_SERVER"),
        _range(2, "10.10.2.0/24", "MEMBER"),
        _range(3, "10.10.3.0/24", "NONE"),
    ]
    effective_networks = [{**row, "options": []} for row in networks]
    effective_ranges = [{**row, "options": []} for row in ranges]
    return CollectionResult(
        grid="LAB",
        records={"network": networks, "range": ranges},
        effective_records={"network": effective_networks, "range": effective_ranges},
    )


def _core_options():
    rows = []
    for index, cidr in enumerate(("10.0.0.0/24", "10.0.1.0/24")):
        ref = f"network/LAB/{index}"
        gateway = f"10.0.{index}.3"
        rows.extend([
            _option("network", ref, 51, "7200"),
            _option("network", ref, 6, "10.31.31.31"),
            _option("network", ref, 15, "sdc.dk"),
            _option("network", ref, 3, gateway),
        ])
    # Same functional value from a different source must not create a new profile.
    duplicate = deepcopy(rows[0])
    duplicate.update({
        "source_level": "Network", "source_ref": "network/LAB/0",
        "configured_here": True, "inherited": False,
    })
    rows.append(duplicate)

    for index in (0, 1):
        ref = f"range/LAB/{index}"
        rows.extend([
            _option("range", ref, 51, "7200"),
            _option("range", ref, 6, "10.31.31.31"),
            _option("range", ref, 15, "sdc.dk"),
            _option("range", ref, 3, f"10.10.{index}.3"),
        ])
    ref = "range/LAB/2"
    rows.extend([
        _option("range", ref, 51, "3600"),
        _option("range", ref, 6, "10.50.0.10,10.50.0.11"),
        _option("range", ref, 15, "corp.example"),
        _option("range", ref, 3, "10.10.2.254"),
    ])
    return rows


@pytest.mark.parametrize(("state", "network", "expected"), [
    ({"status": "NOT_CONFIGURED"}, {"network": "10.0.0.0/24"}, "NOT_CONFIGURED"),
    ({"status": "UNRESOLVED"}, {"network": "10.0.0.0/24"}, "UNRESOLVED"),
    ({"status": "VALUE", "value": ""}, {"network": "10.0.0.0/24"}, "EMPTY_VALUE"),
    ({"status": "VALUE", "value": "not-an-ip"}, {"network": "10.0.0.0/24"}, "INVALID_VALUE"),
    ({"status": "VALUE", "value": "10.0.0.1"}, {"network": "10.0.0.0/24"}, "FIRST_USABLE"),
    ({"status": "VALUE", "value": "10.0.0.254"}, {"network": "10.0.0.0/24"}, "LAST_USABLE"),
    ({"status": "VALUE", "value": "10.0.0.3"}, {"network": "10.0.0.0/24"}, "HOST_OFFSET_3"),
    ({"status": "VALUE", "value": "10.0.1.3"}, {"network": "10.0.0.0/24"}, "OUTSIDE_SUBNET"),
    ({"status": "VALUE", "value": "10.0.0.2,10.0.0.3"}, {"network": "10.0.0.0/24"}, "MULTIPLE_ROUTERS"),
])
def test_gateway_convention_is_structural_not_literal(state, network, expected):
    derived = _gateway_convention(state, network)
    assert derived["status"] in {"VALUE", "NOT_CONFIGURED", "UNRESOLVED"}
    assert (derived.get("value") if derived["status"] == "VALUE" else derived["status"]) == expected


def test_exact_network_and_range_profiles_are_deterministic_and_segmented():
    result = _result()
    options = _core_options()
    summary, profiles, objects = build_profile_discovery([result], [], options)

    by_type = {row["Profile Type"]: row for row in summary}
    assert list(by_type["Network"]) == PROFILE_DISCOVERY_HEADERS
    assert by_type["Network"]["Applicable Objects"] == 3
    assert by_type["Network"]["Profiled Objects"] == 2
    assert by_type["Network"]["Unresolved Objects"] == 1
    assert by_type["Network"]["Distinct Profiles"] == 1
    assert by_type["Network"]["Top-1 Share %"] == 100.0

    assert by_type["Range"]["Applicable Objects"] == 3
    assert by_type["Range"]["Profiled Objects"] == 3
    assert by_type["Range"]["Distinct Profiles"] == 2
    assert by_type["Range"]["Not Applicable Objects"] == 1
    assert by_type["Range"]["Top-1 Share %"] == pytest.approx(66.7)

    assert all(list(row) == PROFILE_HEADERS for row in profiles)
    network_profile = next(row for row in profiles if row["Profile Type"] == "Network")
    assert network_profile["Profiled Objects"] == 2
    assert network_profile["Gateway Convention"] == "HOST_OFFSET_3"
    assert network_profile["Fingerprint ID"].startswith("NET-FP1-")
    range_profiles = [row for row in profiles if row["Profile Type"] == "Range"]
    assert {row["Association Family"] for row in range_profiles} == {"MS_SERVER", "MEMBER"}

    assert all(list(row) == PROFILE_OBJECT_HEADERS for row in objects)
    unresolved = next(row for row in objects if row["Object Ref"] == "network/LAB/2")
    assert unresolved["Profile Status"] == "UNRESOLVED_PROFILE_INPUTS"
    assert set(unresolved["Missing Inputs"].split(", ")) == {
        "lease_time", "dns_servers", "domain_name", "gateway_convention"
    }
    none_range = next(row for row in objects if row["Object Ref"] == "range/LAB/3")
    assert none_range["Association Family"] == "NONE"
    assert none_range["Profile Status"] == "NOT_APPLICABLE_TO_DHCP_PROFILE"


def test_unknown_range_association_is_visible_not_forced_into_a_profile():
    result = _result()
    unknown = _range(4, "10.10.4.0/24", "FUTURE_ASSOCIATION")
    result.records["range"].append(unknown)
    result.effective_records["range"].append({**unknown, "options": []})
    summary, _profiles, objects = build_profile_discovery([result], [], _core_options())
    range_summary = next(row for row in summary if row["Profile Type"] == "Range")
    assert range_summary["Applicable Objects"] == 3
    assert range_summary["Unresolved Association Objects"] == 1
    row = next(item for item in objects if item["Object Ref"] == "range/LAB/4")
    assert row["Association Family"] == "OTHER"
    assert row["Profile Status"] == "UNRESOLVED_ASSOCIATION"
    assert row["Missing Inputs"] == "association_family"


def test_fingerprint_ids_do_not_depend_on_normalized_row_order_or_source_metadata_order():
    result = _result()
    options = _core_options()
    first = build_profile_discovery([result], [], options)
    second = build_profile_discovery([result], [], list(reversed(options)))
    assert first == second


def test_empty_string_is_a_real_value_state_not_not_configured_or_unresolved():
    result = _result()
    options = _core_options()
    dns = next(row for row in options
               if row["object_ref"] == "network/LAB/0" and row["option_number"] == 6)
    dns["effective_value"] = ""
    summary, profiles, objects = build_profile_discovery([result], [], options)
    network_rows = [row for row in objects if row["Profile Type"] == "Network"
                    and row["Profile Status"] == "PROFILED"]
    assert len(network_rows) == 2
    empty = next(row for row in network_rows if row["Object Ref"] == "network/LAB/0")
    assert empty["DNS Servers"] == "EMPTY_STRING"
    assert next(row for row in summary if row["Profile Type"] == "Network")["Distinct Profiles"] == 2
    assert any('"value":""' in row["Canonical Payload"] for row in profiles
               if row["Profile Type"] == "Network")


def test_usefulness_reports_invariant_vs_variable_without_a_score():
    result = _result()
    options = _core_options()
    rows = build_profile_usefulness([result], [], options)
    assert all(list(row) == PROFILE_USEFULNESS_HEADERS for row in rows)

    lease = next(row for row in rows if row["Parameter ID"] == "dhcp.lease_time.network")
    assert lease["Population Objects"] == 3
    assert lease["Resolved Objects"] == 2
    assert lease["Distinct Resolved States"] == 1
    assert lease["Invariant Among Resolved"] is True
    assert lease["Core Fingerprint v1"] == "YES"
    assert lease["Observed Role"] == "CORE_FINGERPRINT_V1"

    range_lease = next(row for row in rows if row["Parameter ID"] == "dhcp.lease_time.range")
    assert range_lease["Population Basis"] == "DHCP_ASSOCIATED_RANGES"
    assert range_lease["Population Objects"] == 3
    assert range_lease["Resolved Objects"] == 3
    assert range_lease["Distinct Resolved States"] == 2


def test_feature_overlays_do_not_change_core_fingerprint_identity():
    result = _result()
    options = _core_options()
    baseline = build_profile_discovery([result], [], options)
    # Option 119 differs between the two otherwise-identical Network objects.
    overlays = [
        _option("network", "network/LAB/0", 119, "example-a"),
        _option("network", "network/LAB/1", 119, "example-b"),
    ]
    changed = build_profile_discovery([result], [], options + overlays)
    baseline_profiles = [row for row in baseline[1] if row["Profile Type"] == "Network"]
    changed_profiles = [row for row in changed[1] if row["Profile Type"] == "Network"]
    assert [row["Fingerprint ID"] for row in baseline_profiles] == [
        row["Fingerprint ID"] for row in changed_profiles
    ]
    assert changed_profiles[0]["Overlay Variable Inputs"] >= 1

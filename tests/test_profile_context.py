"""Profile context and parent Network↔Range relationship regressions."""
import json

from infoblox_inventory.models import CollectionResult
from infoblox_inventory.profile_context import build_profile_context, build_profile_relationships


def _option(object_ref, parameter, number, value, source_level, source_ref):
    return {
        "grid": "LAB", "object_type": "network", "object_ref": object_ref,
        "object_name": "10.0.0.0/24", "network_view": "default",
        "parent_network": "10.0.0.0/24", "parameter": parameter,
        "option_number": number, "vendor_class": "DHCP", "effective_value": value,
        "configured_here": source_level == "Network",
        "inherited": source_level != "Network", "multisource": False,
        "source_level": source_level, "source_object": "source",
        "source_ref": source_ref, "status": "COMPLETE",
    }


def _fixture():
    net0 = {
        "_ref": "network/LAB/0", "network": "10.0.0.0/24", "network_view": "default",
        "comment": "documented", "extattrs": {"Site": {"value": "A"}},
    }
    net1 = {
        "_ref": "network/LAB/1", "network": "10.0.1.0/24", "network_view": "default",
        "extattrs": {},
    }
    ranges = [
        {
            "_ref": "range/LAB/0", "network": "10.0.0.0/24", "network_view": "default",
            "start_addr": "10.0.0.10", "end_addr": "10.0.0.20",
            "server_association_type": "MS_SERVER", "extattrs": {},
        },
        {
            "_ref": "range/LAB/1", "network": "10.0.1.0/24", "network_view": "default",
            "start_addr": "10.0.1.10", "end_addr": "10.0.1.20",
            "server_association_type": "MEMBER", "extattrs": {},
        },
        {
            "_ref": "range/LAB/2", "network": "10.0.1.0/24", "network_view": "default",
            "start_addr": "10.0.1.30", "end_addr": "10.0.1.40",
            "server_association_type": "NONE", "extattrs": {},
        },
    ]
    result = CollectionResult(
        grid="LAB",
        records={"network": [net0, net1], "range": ranges},
        effective_records={"network": [net0, net1], "range": ranges},
    )
    assignments = [
        {
            "Profile": "Network Profile v1", "Grid": "LAB", "Scope": "Network",
            "Object Ref": "network/LAB/0", "Object": "10.0.0.0/24",
            "Network View": "default", "Association Family": "",
            "Population Status": "PROFILED", "Fingerprint ID": "NET-FP1-a",
            "Network Relevance Reasons": "active_option, members, range_parent",
        },
        {
            "Profile": "Network Profile v1", "Grid": "LAB", "Scope": "Network",
            "Object Ref": "network/LAB/1", "Object": "10.0.1.0/24",
            "Network View": "default", "Association Family": "",
            "Population Status": "UNRESOLVED_PROFILE_INPUTS", "Fingerprint ID": "",
            "Network Relevance Reasons": "range_parent",
        },
        {
            "Profile": "Range Profile v1", "Grid": "LAB", "Scope": "Range",
            "Object Ref": "range/LAB/0", "Object": "10.0.0.10-10.0.0.20",
            "Network View": "default", "Association Family": "MS_SERVER",
            "Population Status": "PROFILED", "Fingerprint ID": "RNG-FP1-a",
        },
        {
            "Profile": "Range Profile v1", "Grid": "LAB", "Scope": "Range",
            "Object Ref": "range/LAB/1", "Object": "10.0.1.10-10.0.1.20",
            "Network View": "default", "Association Family": "MEMBER",
            "Population Status": "PROFILED", "Fingerprint ID": "RNG-FP1-b",
        },
        {
            "Profile": "Range Profile v1", "Grid": "LAB", "Scope": "Range",
            "Object Ref": "range/LAB/2", "Object": "10.0.1.30-10.0.1.40",
            "Network View": "default", "Association Family": "NONE",
            "Population Status": "NOT_APPLICABLE_TO_DHCP_PROFILE", "Fingerprint ID": "",
        },
    ]
    options = []
    for parameter, number, value in (
        ("dhcp-lease-time", 51, "7200"),
        ("domain-name-servers", 6, "192.0.2.53"),
        ("domain-name", 15, "lab.example"),
        ("routers", 3, "10.0.0.3"),
    ):
        options.extend([
            _option("network/LAB/0", parameter, number, value, "Grid", "grid:dhcpproperties/LAB"),
            _option("network/LAB/0", parameter, number, value, "Network", "network/LAB/0"),
        ])
    return result, assignments, options


def test_profile_context_keeps_functional_identity_separate_from_context():
    result, assignments, options = _fixture()
    rows = build_profile_context([result], [], options, assignments)
    network = next(row for row in rows if row["Fingerprint ID"] == "NET-FP1-a")
    assert network["Object Count"] == 1
    assert json.loads(network["Network View Distribution"]) == {"default": 1}
    assert json.loads(network["Network Relevance Reason Distribution"]) == {
        "active_option": 1, "members": 1, "range_parent": 1,
    }
    assert json.loads(network["EA Key Presence"]) == {"Site": 1}
    assert json.loads(network["EA Top Values"]) == {"Site": {'"A"': 1}}
    assert network["Comment Present Objects"] == 1
    assert network["Comment Present %"] == 100.0
    source = json.loads(network["Core Source Signature Distribution"])
    assert source["lease_time"] == {"Grid+Network": 1}
    assert source["dns_servers"] == {"Grid+Network": 1}
    assert source["domain_name"] == {"Grid+Network": 1}
    assert source["gateway_convention"] == {"Grid+Network": 1}


def test_network_range_relationships_keep_unresolved_parent_and_none_range_explicit():
    result, assignments, _options = _fixture()
    summary, detail = build_profile_relationships([result], assignments)

    assert len(detail) == 3
    by_range = {row["Range"]: row for row in detail}
    first = by_range["10.0.0.10-10.0.0.20"]
    assert first["Relationship Status"] == "PROFILE_PAIR"
    assert first["Parent Network Fingerprint ID"] == "NET-FP1-a"
    assert first["Range Fingerprint ID"] == "RNG-FP1-a"

    second = by_range["10.0.1.10-10.0.1.20"]
    assert second["Relationship Status"] == "PARENT_PROFILE_UNRESOLVED"
    assert second["Range Fingerprint ID"] == "RNG-FP1-b"

    none = by_range["10.0.1.30-10.0.1.40"]
    assert none["Relationship Status"] == "RANGE_NOT_APPLICABLE"

    assert sum(row["Range Count"] for row in summary) == 2
    pair = next(row for row in summary if row["Relationship Status"] == "PROFILE_PAIR")
    unresolved = next(row for row in summary if row["Relationship Status"] == "PARENT_PROFILE_UNRESOLVED")
    assert pair["Range Count"] == unresolved["Range Count"] == 1
    assert pair["Share of Associated Ranges %"] == 50.0
    assert pair["Share of Paired Profiled Ranges %"] == 100.0
    assert unresolved["Share of Paired Profiled Ranges %"] is None

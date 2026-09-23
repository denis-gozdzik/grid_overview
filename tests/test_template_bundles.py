"""Template bundle analysis exposes provisioning relationships without losing evidence."""
from infoblox_inventory.models import CollectionResult
from infoblox_inventory.template_bundles import build_template_bundles
from infoblox_inventory.template_semantics import build_template_semantic_model
from infoblox_inventory.topology import normalize_topology


def _build(records):
    result = CollectionResult(grid="LAB", records=records)
    topology = normalize_topology(result)
    _models, assignments, _matrix, _semantics, _headers = build_template_semantic_model(
        topology, ["LAB"]
    )
    return build_template_bundles(topology, assignments)


def test_linked_ms_bundle_derives_geometry_and_disabled_option_flag():
    rows = _build({
        "networktemplate": [{
            "_ref": "networktemplate/ms:one",
            "name": "wifi-24",
            "netmask": 24,
            "members": [{"_struct": "msdhcpserver", "ipv4addr": "ms.example"}],
            "range_templates": ["wifi-range"],
        }],
        "rangetemplate": [{
            "_ref": "rangetemplate/ms:one",
            "name": "wifi-range",
            "offset": 4,
            "number_of_addresses": 251,
            "server_association_type": "MS_SERVER",
            "ms_server": {"_struct": "msdhcpserver", "ipv4addr": "ms.example"},
            "exclude": [{"offset": 248, "number_of_addresses": 3}],
            "use_options": False,
            "options": [{
                "num": 51, "name": "dhcp-lease-time", "vendor_class": "DHCP",
                "value": "7200", "use_option": True,
            }],
        }],
    })

    assert len(rows) == 1
    row = rows[0]
    assert row["Bundle Status"] == "LINKED"
    assert row["Provisioning Family"] == "MS_SERVER"
    assert row["Network Prefix"] == "/24"
    assert row["Network Member Family"] == "MS_SERVER"
    assert row["Range Association"] == "MS_SERVER"
    assert row["Range Start"] == "HOST_OFFSET_4"
    assert row["Range Addresses"] == "251"
    assert row["Range End"] == "LAST_USABLE"
    assert "offset 248, count 3" in row["Exclusion Pattern"]
    assert row["Options State"] == "DISABLED (use_options=False)"
    assert row["Stored Enabled Options"] == "dhcp-lease-time"
    assert "STORED_OPTIONS_DISABLED_BY_CONTAINER" in row["Review Flags"]


def test_none_association_with_member_reference_is_flagged():
    rows = _build({
        "networktemplate": [{
            "_ref": "networktemplate/ib:one",
            "name": "ib-net",
            "netmask": 24,
            "members": [{"_struct": "dhcpmember", "name": "member-a"}],
            "range_templates": ["ib-range"],
        }],
        "rangetemplate": [{
            "_ref": "rangetemplate/ib:one",
            "name": "ib-range",
            "offset": 100,
            "number_of_addresses": 120,
            "server_association_type": "NONE",
            "member": {"_struct": "dhcpmember", "name": "member-a"},
        }],
    })

    assert len(rows) == 1
    row = rows[0]
    assert row["Provisioning Family"] == "MIXED_OR_INCONSISTENT"
    assert "NETWORK_RANGE_ASSOCIATION_MISMATCH" in row["Review Flags"]
    assert "ASSOCIATION_NONE_WITH_SERVER_REFERENCE" in row["Review Flags"]


def test_orphan_range_template_remains_visible():
    rows = _build({
        "networktemplate": [],
        "rangetemplate": [{
            "_ref": "rangetemplate/orphan:one",
            "name": "orphan-range",
            "offset": 1,
            "number_of_addresses": 20,
            "server_association_type": "MS_SERVER",
            "ms_server": {"_struct": "msdhcpserver", "ipv4addr": "ms.example"},
        }],
    })

    assert len(rows) == 1
    row = rows[0]
    assert row["Bundle Status"] == "ORPHAN_RANGE_TEMPLATE"
    assert row["Network Template"] == ""
    assert row["Range Template"] == "orphan-range"
    assert "not referenced" in row["Notes"]


def test_missing_linked_range_is_not_silently_dropped():
    rows = _build({
        "networktemplate": [{
            "_ref": "networktemplate/missing:one",
            "name": "network-one",
            "netmask": 24,
            "range_templates": ["missing-range"],
        }],
        "rangetemplate": [],
    })

    assert len(rows) == 1
    row = rows[0]
    assert row["Bundle Status"] == "MISSING_RANGE_TEMPLATE"
    assert row["Range Template"] == "missing-range"
    assert "not collected/found" in row["Notes"]

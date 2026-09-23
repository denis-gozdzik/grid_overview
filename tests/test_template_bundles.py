"""Template bundle analysis exposes provisioning relationships without losing evidence."""
from infoblox_inventory.models import CollectionResult
from infoblox_inventory.template_bundles import (
    build_template_bundle_models, build_template_bundles,
)
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


def test_relative_geometry_collapses_24_and_27_but_keeps_28_variant():
    def bundle(prefix, offset, count, ex_offset):
        records = {
            "networktemplate": [{
                "_ref": f"networktemplate/{prefix}",
                "name": f"wifi-{prefix}",
                "netmask": prefix,
                "members": [{"_struct": "msdhcpserver", "ipv4addr": "ms.example"}],
                "range_templates": [f"wifi-{prefix}-range"],
            }],
            "rangetemplate": [{
                "_ref": f"rangetemplate/{prefix}",
                "name": f"wifi-{prefix}-range",
                "offset": offset,
                "number_of_addresses": count,
                "server_association_type": "MS_SERVER",
                "ms_server": {"_struct": "msdhcpserver", "ipv4addr": "ms.example"},
                "exclude": [{"offset": ex_offset, "number_of_addresses": 3}],
            }],
        }
        result = CollectionResult(grid=f"G{prefix}", records=records)
        topology = normalize_topology(result)
        _models, assignments, _matrix, _semantics, _headers = build_template_semantic_model(
            topology, [f"G{prefix}"]
        )
        return build_template_bundles(topology, assignments)[0]

    row24 = bundle(24, 4, 251, 248)
    row27 = bundle(27, 4, 27, 24)
    row28 = bundle(28, 2, 13, 10)

    assert row24["Geometry Signature"] == row27["Geometry Signature"]
    assert row24["Bundle Model ID"] == row27["Bundle Model ID"]
    assert row28["Geometry Signature"] != row24["Geometry Signature"]
    assert row28["Bundle Model ID"] != row24["Bundle Model ID"]

    rows = [row24, row27, row28]
    models = build_template_bundle_models(rows, ["G24", "G27", "G28"])
    common = next(row for row in models if row["Bundle Model ID"] == row24["Bundle Model ID"])
    assert common["Bundle Count"] == 2
    assert common["Grid Count"] == 2
    assert common["Grid Coverage %"] == 66.7


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

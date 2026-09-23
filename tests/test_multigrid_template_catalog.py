"""Nine-Grid template catalog behavior: local values parameterize, policy differences split."""
from infoblox_inventory.models import CollectionResult
from infoblox_inventory.template_bundles import (
    build_template_bundle_models, build_template_bundles,
)
from infoblox_inventory.template_semantics import build_template_semantic_model
from infoblox_inventory.topology import normalize_topology


def _grid_result(index: int, *, lease: str = "7200") -> CollectionResult:
    grid = f"GRID-{index}"
    prefix = 24 if index % 2 else 27
    if prefix == 24:
        range_count = 251
        exclusion_offset = 248
    else:
        range_count = 27
        exclusion_offset = 24

    member_name = f"msdhcp-{index}.example.net"
    dns = f"10.{index}.0.10,10.{index}.0.11"
    domain = f"grid{index}.example.net"
    gateway = f"10.{index}.0.3"

    network_name = f"{grid}-BRANCH-{prefix}"
    range_name = f"{grid}-BRANCH-{prefix}-RANGE"

    shared_options = [
        {
            "num": 51, "name": "dhcp-lease-time", "vendor_class": "DHCP",
            "value": lease, "use_option": True,
        },
        {
            "num": 6, "name": "domain-name-servers", "vendor_class": "DHCP",
            "value": dns, "use_option": True,
        },
        {
            "num": 15, "name": "domain-name", "vendor_class": "DHCP",
            "value": domain, "use_option": True,
        },
        {
            "num": 3, "name": "routers", "vendor_class": "DHCP",
            "value": gateway, "use_option": True,
        },
    ]

    return CollectionResult(
        grid=grid,
        records={
            "networktemplate": [{
                "_ref": f"networktemplate/{grid}:branch",
                "name": network_name,
                "netmask": prefix,
                "allow_any_netmask": False,
                "members": [{
                    "_struct": "msdhcpserver",
                    "name": member_name,
                    "ipv4addr": f"10.{index}.255.10",
                }],
                "range_templates": [range_name],
                "use_options": True,
                "options": list(shared_options),
            }],
            "rangetemplate": [{
                "_ref": f"rangetemplate/{grid}:branch",
                "name": range_name,
                "offset": 4,
                "number_of_addresses": range_count,
                "server_association_type": "MS_SERVER",
                "ms_server": {
                    "_struct": "msdhcpserver",
                    "name": member_name,
                    "ipv4addr": f"10.{index}.255.10",
                },
                "exclude": [{
                    "offset": exclusion_offset,
                    "number_of_addresses": 3,
                }],
                "use_options": True,
                "options": list(shared_options),
            }],
        },
    )


def _catalog(results: list[CollectionResult]):
    grids = [result.grid for result in results]
    topology = [
        record
        for result in results
        for record in normalize_topology(result)
    ]
    template_models, assignments, matrix, _semantics, headers = (
        build_template_semantic_model(topology, grids)
    )
    bundles = build_template_bundles(topology, assignments)
    bundle_models = build_template_bundle_models(bundles, grids)
    return template_models, matrix, headers, bundles, bundle_models


def test_nine_grids_share_one_bundle_model_despite_local_values_and_prefixes():
    results = [_grid_result(index) for index in range(1, 10)]

    template_models, matrix, headers, bundles, bundle_models = _catalog(results)

    assert len(bundle_models) == 1
    model = bundle_models[0]
    assert model["Bundle Count"] == 9
    assert model["Grid Count"] == 9
    assert model["Grid Coverage %"] == 100.0
    assert model["Provisioning Family"] == "MS_SERVER"
    assert model["Network Prefixes"] == "/24, /27"
    assert model["Attention"] == "OK"
    assert model["Model Signature"] == (
        "MS_SERVER | /24,/27 | +4→LAST_USABLE; excl3@tail-5"
    )

    assert len(bundles) == 9
    assert len({row["Bundle Model ID"] for row in bundles}) == 1
    assert all(row["Attention"] == "OK" for row in bundles)

    network_models = [
        row for row in template_models if row["Template Type"] == "networktemplate"
    ]
    range_models = [
        row for row in template_models if row["Template Type"] == "rangetemplate"
    ]
    assert len(network_models) == 1
    assert len(range_models) == 1
    assert network_models[0]["Grid Count"] == 9
    assert range_models[0]["Grid Count"] == 9

    assert all(f"GRID-{index}" in headers for index in range(1, 10))
    dns_row = next(
        row for row in matrix
        if row["Template Type"] == "rangetemplate"
        and row["Parameter"] == "dhcp.dns_servers"
    )
    for index in range(1, 10):
        assert f"10.{index}.0.10" in dns_row[f"GRID-{index}"]


def test_one_grid_policy_difference_splits_multigrid_bundle_model():
    results = [
        _grid_result(index, lease="3600" if index == 9 else "7200")
        for index in range(1, 10)
    ]

    _template_models, _matrix, _headers, bundles, bundle_models = _catalog(results)

    assert len(bundle_models) == 2
    counts = sorted(
        (row["Grid Count"], row["Bundle Count"], row["Grid Coverage %"])
        for row in bundle_models
    )
    assert counts == [(1, 1, 11.1), (8, 8, 88.9)]
    assert len({row["Bundle Model ID"] for row in bundles}) == 2

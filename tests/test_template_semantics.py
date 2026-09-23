"""Template Semantic Model v1 must group by reusable shape, not Grid-local literals."""
from copy import deepcopy

from infoblox_inventory.models import CollectionResult
from infoblox_inventory.template_semantics import (
    ACTIVE, GRID_LOCAL, INACTIVE, POLICY_LITERAL, TOPOLOGY_DERIVED,
    build_template_semantic_model, template_semantic_rows,
)
from infoblox_inventory.topology import normalize_topology


def _network_template(grid, *, lease="7200", dns="10.0.0.10,10.0.0.11",
                      domain="a.example", gateway="10.1.0.3",
                      ddns_enabled=True, ddns_domain="a.example",
                      member_name="m-a", member_struct="dhcpmember", dns_use=True):
    return CollectionResult(
        grid=grid,
        records={
            "networktemplate": [{
                "_ref": f"networktemplate/{grid}:branch",
                "name": f"{grid}_BRANCH",
                "use_options": True,
                "options": [
                    {"num": 51, "name": "dhcp-lease-time", "value": lease,
                     "vendor_class": "DHCP", "use_option": True},
                    {"num": 6, "name": "domain-name-servers", "value": dns,
                     "vendor_class": "DHCP", "use_option": dns_use},
                    {"num": 15, "name": "domain-name", "value": domain,
                     "vendor_class": "DHCP", "use_option": True},
                    {"num": 3, "name": "routers", "value": gateway,
                     "vendor_class": "DHCP", "use_option": True},
                ],
                "enable_ddns": ddns_enabled,
                "use_enable_ddns": True,
                "ddns_domainname": ddns_domain,
                "use_ddns_domainname": True,
                "ddns_generate_hostname": False,
                "use_ddns_generate_hostname": True,
                "netmask": 24,
                "allow_any_netmask": False,
                "members": [{"name": member_name, "_struct": member_struct}],
            }],
            "rangetemplate": [],
        },
    )


def _records(*results):
    return [record for result in results for record in normalize_topology(result)]


def test_grid_local_values_collapse_to_one_network_template_shape():
    a = _network_template(
        "GRID-A", dns="10.1.1.10,10.1.1.11", domain="dk.example",
        gateway="10.20.0.3", ddns_domain="dk.example", member_name="member-a",
    )
    b = _network_template(
        "GRID-B", dns="10.2.2.10,10.2.2.11", domain="se.example",
        gateway="10.30.0.3", ddns_domain="se.example", member_name="member-b",
    )

    models, assignments, matrix, semantics, headers = build_template_semantic_model(
        _records(a, b), ["GRID-A", "GRID-B"]
    )

    assert len(models) == 1
    model = models[0]
    assert model["Template Type"] == "networktemplate"
    assert model["Template Count"] == 2
    assert model["Grid Count"] == 2
    assert model["Grid Coverage %"] == 100.0
    assert model["Model ID"].startswith("NTPL-SH1-")
    assert len({row["Model ID"] for row in assignments}) == 1

    dns = [row for row in semantics if row["Parameter"] == "dhcp.dns_servers"]
    assert {row["Parameterization Role"] for row in dns} == {GRID_LOCAL}
    assert {row["Activity State"] for row in dns} == {ACTIVE}
    assert {row["Shape Value"]["cardinality"] for row in dns} == {2}
    assert len({str(row["Stored Value"]) for row in dns}) == 2

    gateway_rows = [row for row in semantics if row["Parameter"] == "dhcp.gateway"]
    assert {row["Parameterization Role"] for row in gateway_rows} == {TOPOLOGY_DERIVED}
    assert len({str(row["Stored Value"]) for row in gateway_rows}) == 2

    assert "GRID-A" in headers and "GRID-B" in headers
    dns_matrix = next(row for row in matrix if row["Parameter"] == "dhcp.dns_servers")
    assert dns_matrix["Activity State"] == ACTIVE
    assert "10.1.1.10" in dns_matrix["GRID-A"]
    assert "10.2.2.10" in dns_matrix["GRID-B"]
    netmask_matrix = next(row for row in matrix if row["Parameter"] == "structure.netmask")
    assert "/24" in netmask_matrix["GRID-A"]
    member_matrix = next(row for row in matrix if row["Parameter"] == "structure.members")
    assert "member-a" in member_matrix["GRID-A"]


def test_empty_local_reference_is_hidden_from_human_grid_matrix():
    result = _network_template("GRID-A")
    result.records["networktemplate"][0]["fixed_address_templates"] = []

    _models, _assignments, matrix, semantics, _headers = build_template_semantic_model(
        _records(result), ["GRID-A"]
    )

    assert any(
        row["Parameter"] == "structure.fixed_address_templates"
        for row in semantics
    )
    assert not any(
        row["Parameter"] == "structure.fixed_address_templates"
        for row in matrix
    )


def test_reference_family_difference_splits_template_shape_but_reference_value_does_not():
    infoblox = _network_template(
        "GRID-A", member_name="ib-a", member_struct="dhcpmember"
    )
    microsoft = _network_template(
        "GRID-B", member_name="ms-b", member_struct="msdhcpserver"
    )

    models, assignments, _matrix, semantics, _headers = build_template_semantic_model(
        _records(infoblox, microsoft), ["GRID-A", "GRID-B"]
    )

    assert len(models) == 2
    assert len({row["Model ID"] for row in assignments}) == 2
    member_rows = [row for row in semantics if row["Parameter"] == "structure.members"]
    assert {
        tuple(row["Shape Value"].get("reference_types", []))
        for row in member_rows
    } == {("dhcpmember",), ("msdhcpserver",)}


def test_policy_literal_difference_creates_different_template_shapes():
    a = _network_template("GRID-A", lease="7200")
    b = _network_template("GRID-B", lease="3600")

    models, assignments, _matrix, semantics, _headers = build_template_semantic_model(
        _records(a, b), ["GRID-A", "GRID-B"]
    )

    assert len(models) == 2
    assert len({row["Model ID"] for row in assignments}) == 2
    lease = [row for row in semantics if row["Parameter"] == "dhcp.lease_time"]
    assert {row["Parameterization Role"] for row in lease} == {POLICY_LITERAL}
    assert {row["Shape Value"] for row in lease} == {"7200", "3600"}


def test_inactive_local_value_does_not_split_shape_or_look_active():
    a = _network_template("GRID-A", dns="10.1.1.10", dns_use=False)
    b = _network_template("GRID-B", dns="10.2.2.10", dns_use=False)

    models, assignments, matrix, semantics, _headers = build_template_semantic_model(
        _records(a, b), ["GRID-A", "GRID-B"]
    )

    assert len(models) == 1
    assert len({row["Model ID"] for row in assignments}) == 1
    dns = [row for row in semantics if row["Parameter"] == "dhcp.dns_servers"]
    assert {row["Activity State"] for row in dns} == {INACTIVE}
    assert all(row["Shape Value"] is None for row in dns)
    dns_matrix = next(row for row in matrix if row["Parameter"] == "dhcp.dns_servers")
    assert dns_matrix["Activity State"] == INACTIVE
    assert "10.1.1.10" in dns_matrix["GRID-A"]
    assert "10.2.2.10" in dns_matrix["GRID-B"]


def test_inactive_and_absent_known_option_share_disabled_shape():
    inactive = _network_template("GRID-A", dns="10.1.1.10", dns_use=False)
    absent = _network_template("GRID-B")
    absent.records["networktemplate"][0]["options"] = [
        option for option in absent.records["networktemplate"][0]["options"]
        if option["num"] != 6
    ]

    models, assignments, _matrix, semantics, _headers = build_template_semantic_model(
        _records(inactive, absent), ["GRID-A", "GRID-B"]
    )

    assert len(models) == 1
    assert len({row["Model ID"] for row in assignments}) == 1
    dns_states = {
        row["Grid"]: row["Activity State"]
        for row in semantics if row["Parameter"] == "dhcp.dns_servers"
    }
    assert dns_states == {"GRID-A": INACTIVE, "GRID-B": "NOT_CONFIGURED"}


def test_network_prefix_is_parameterized_not_a_model_split():
    a = _network_template("GRID-A")
    b = _network_template("GRID-B")
    a.records["networktemplate"][0]["netmask"] = 24
    b.records["networktemplate"][0]["netmask"] = 27

    models, assignments, _matrix, semantics, _headers = build_template_semantic_model(
        _records(a, b), ["GRID-A", "GRID-B"]
    )

    assert len(models) == 1
    assert len({row["Model ID"] for row in assignments}) == 1
    netmask_rows = [row for row in semantics if row["Parameter"] == "structure.netmask"]
    assert {row["Parameterization Role"] for row in netmask_rows} == {TOPOLOGY_DERIVED}
    assert {row["Shape Value"]["cardinality"] for row in netmask_rows} == {1}


def test_non_dhcp_option_code_collision_stays_generic():
    result = _network_template("GRID-A")
    raw = result.records["networktemplate"][0]
    raw["options"].append({
        "num": 6, "name": "custom-six", "value": "opaque",
        "vendor_class": "VENDOR-X", "use_option": True,
    })
    rows = template_semantic_rows(_records(result))

    dns = [row for row in rows if row["Parameter"] == "dhcp.dns_servers"]
    custom = [row for row in rows if row["Parameter"] == "option.VENDOR-X.6"]
    assert len(dns) == 1
    assert len(custom) == 1
    assert custom[0]["Parameterization Role"] == POLICY_LITERAL
    assert custom[0]["Shape Value"] == "opaque"


def test_model_is_deterministic_when_template_and_option_order_changes():
    a = _network_template("GRID-A")
    b = _network_template("GRID-B", dns="10.9.9.9,10.9.9.10", domain="b.example",
                          ddns_domain="b.example", member_name="member-b")
    records = _records(a, b)

    first = build_template_semantic_model(records, ["GRID-A", "GRID-B"])
    reversed_records = list(reversed(deepcopy(records)))
    for record in reversed_records:
        if getattr(record, "options", None):
            record.options = list(reversed(record.options))
    second = build_template_semantic_model(reversed_records, ["GRID-A", "GRID-B"])

    assert {
        (row["Model ID"], row["Canonical Shape"], row["Full SHA256"])
        for row in first[0]
    } == {
        (row["Model ID"], row["Canonical Shape"], row["Full SHA256"])
        for row in second[0]
    }
    assert sorted((row["Grid"], row["Model ID"]) for row in first[1]) == sorted(
        (row["Grid"], row["Model ID"]) for row in second[1]
    )

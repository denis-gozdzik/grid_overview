"""Synthetic populated examples constrained by the captured LAB runtime schemas.

These cases verify formats/types, not the presence of these objects in the LAB.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from infoblox_inventory.collectors.topology import TOPOLOGY_OBJECTS
from infoblox_inventory.models import CollectionResult
from infoblox_inventory.topology import (
    DHCPFailoverRecord, DHCPOption, DHCPOptionDefinitionRecord, DHCPOptionSpaceRecord,
    FixedAddressTemplateRecord, MemberAssociation, MSServerAssociation,
    NetworkTemplateRecord, RangeExclusion, RangeTemplateRecord, TOPOLOGY_SHEETS,
    normalize_topology, topology_coverage, topology_excel_rows, topology_headers,
    topology_option_rows,
)


SCHEMAS = Path(__file__).parent / "fixtures" / "topology_lab_20260920" / "schemas"
SYNTHETIC_POPULATED_ROWS = {
    "dhcpfailover": [{
        "_ref": "dhcpfailover/synthetic:pair", "name": "synthetic-pair",
        "association_type": "GRID", "primary": "synthetic-primary.example",
        "secondary": "synthetic-secondary.example", "primary_server_type": "GRID",
        "secondary_server_type": "EXTERNAL", "primary_state": "NORMAL",
        "secondary_state": "COMMUNICATIONS_INTERRUPTED", "failover_port": 647,
        "use_failover_port": False, "max_client_lead_time": 3600,
        "ms_server": "192.0.2.20", "ms_enable_authentication": False,
    }],
    "networktemplate": [{
        "_ref": "networktemplate/synthetic:network", "name": "synthetic-network",
        "netmask": 24, "allow_any_netmask": False,
        "members": [{"name": "synthetic-primary.example", "ipv4addr": "192.0.2.10"},
                    {"ipv4addr": "192.0.2.20"}],
        "delegated_member": {"name": "synthetic-primary.example"},
        "range_templates": ["synthetic-range"],
        "fixed_address_templates": ["synthetic-fixed-template"],
        "authority": False, "use_authority": True, "lease_scavenge_time": -1,
        "use_lease_scavenge_time": False, "use_options": False,
        "options": [{"num": 51, "name": "dhcp-lease-time", "value": "43200",
                     "vendor_class": "DHCP", "use_option": True}],
    }],
    "rangetemplate": [{
        "_ref": "rangetemplate/synthetic:range", "name": "synthetic-range",
        "offset": 10, "number_of_addresses": 100, "server_association_type": "FAILOVER",
        "failover_association": "synthetic-pair",
        "member": {"name": "synthetic-primary.example", "ipv6addr": "2001:db8::10"},
        "ms_server": {"ipv4addr": "192.0.2.20"},
        "exclude": [{"offset": 20, "number_of_addresses": 2, "comment": "synthetic exclusion"}],
        "bootfile": "boot.efi", "use_bootfile": True, "bootserver": "192.0.2.30",
        "nextserver": "192.0.2.31", "use_nextserver": False, "use_options": True,
        "options": [{"num": 3, "value": "192.0.2.1", "use_option": False}],
    }],
    "fixedaddresstemplate": [{
        "_ref": "fixedaddresstemplate/synthetic:fixed", "name": "synthetic-fixed-template",
        "offset": 2, "number_of_addresses": 4, "enable_pxe_lease_time": True,
        "pxe_lease_time": 600, "use_pxe_lease_time": False, "deny_bootp": False,
        "ignore_dhcp_option_list_request": True, "options": [],
    }],
    "dhcpoptionspace": [{
        "_ref": "dhcpoptionspace/synthetic:vendor", "name": "synthetic-vendor",
        "comment": "Synthetic unit-test example", "space_type": "VENDOR_SPACE",
        "option_definitions": ["dhcpoptiondefinition/synthetic:vendor-option"],
    }],
    "dhcpoptiondefinition": [{
        "_ref": "dhcpoptiondefinition/synthetic:vendor-option", "name": "vendor-option",
        "code": 224, "space": "synthetic-vendor", "type": "string",
    }],
}


def _normalize(object_type, raw):
    return normalize_topology(CollectionResult(grid="SYNTHETIC", records={object_type: [raw]}))[0]


def test_synthetic_populated_records_keep_types_and_stored_values():
    result = CollectionResult(grid="SYNTHETIC", records=deepcopy(SYNTHETIC_POPULATED_ROWS))
    records = normalize_topology(result)
    failover, network, range_template, fixed, space, definition = records
    assert isinstance(failover, DHCPFailoverRecord)
    assert isinstance(network, NetworkTemplateRecord)
    assert isinstance(range_template, RangeTemplateRecord)
    assert isinstance(fixed, FixedAddressTemplateRecord)
    assert isinstance(space, DHCPOptionSpaceRecord)
    assert isinstance(definition, DHCPOptionDefinitionRecord)
    assert all(record.status == "COMPLETE" and not record.issues for record in records)
    assert all(record.data_representation == "RAW_CONFIGURATION" for record in records)
    assert network.lease_scavenge_time == -1
    assert network.authority is False and network.use_authority is True
    assert isinstance(network.members[0], MemberAssociation)
    # An address-only member is not invented as either Grid or Microsoft type.
    assert network.members[1].name is None
    assert network.members[1].ipv4addr == "192.0.2.20"
    assert isinstance(network.options[0], DHCPOption)
    assert network.options[0].value == "43200" and network.use_options is False
    assert isinstance(range_template.ms_server, MSServerAssociation)
    assert isinstance(range_template.exclude[0], RangeExclusion)
    assert range_template.exclude[0].offset == 20
    assert range_template.failover_association == "synthetic-pair"
    assert failover.ms_server == "192.0.2.20"
    assert fixed.options == [] and fixed.use_options is None
    assert definition.code == 224 and definition.space == space.name


def test_unknown_top_level_and_nested_data_and_input_are_preserved_independently():
    raw = deepcopy(SYNTHETIC_POPULATED_ROWS["networktemplate"][0])
    raw["future_field"] = {"values": [1, "unknown"]}
    raw["options"][0]["future_option"] = {"unknown": True}
    raw["members"][0]["future_member"] = ["opaque"]
    before = deepcopy(raw)
    record = _normalize("networktemplate", raw)
    assert raw == before
    assert record.raw == before and record.raw is not raw
    assert record.extra_fields == {"future_field": {"values": [1, "unknown"]}}
    assert record.options[0].extra_fields == {"future_option": {"unknown": True}}
    assert record.members[0].extra_fields == {"future_member": ["opaque"]}
    record.extra_fields["future_field"]["values"].append(2)
    record.options[0].raw["future_option"]["unknown"] = False
    assert raw == before and record.raw == before


@pytest.mark.parametrize("object_type, field, value", [
    ("networktemplate", "netmask", True),
    ("networktemplate", "netmask", -1),
    ("networktemplate", "netmask", "24"),
    ("networktemplate", "lease_scavenge_time", False),
    ("networktemplate", "allow_any_netmask", "false"),
    ("networktemplate", "use_options", 0),
    ("networktemplate", "members", {}),
    ("networktemplate", "delegated_member", "member/example"),
    ("networktemplate", "range_templates", "template"),
    ("rangetemplate", "offset", 10.0),
    ("rangetemplate", "ms_server", "192.0.2.20"),
    ("rangetemplate", "exclude", {}),
    ("dhcpfailover", "ms_server", {"ipv4addr": "192.0.2.20"}),
    ("dhcpoptiondefinition", "code", False),
    ("dhcpoptionspace", "space_type", 10),
    ("fixedaddresstemplate", "options", None),
    ("fixedaddresstemplate", "name", []),
])
def test_wrong_types_are_partial_without_coercion(object_type, field, value):
    raw = {"name": "synthetic", field: value}
    record = _normalize(object_type, raw)
    assert getattr(record, field) is None
    assert record.raw == raw
    assert record.status == "PARTIAL"
    assert any(issue.startswith(field + ":") for issue in record.issues)
    coverage = topology_coverage([record])[0]
    assert coverage["Query"] == "normalization"
    assert coverage["Object"] == object_type
    assert coverage["Collection Status"] == "PARTIAL"
    assert coverage["Objects Found"] == 1 and coverage["Partial Objects"] == 1


def test_nested_invalid_values_remain_visible_in_raw_and_coverage():
    raw = {
        "name": "synthetic-range", "_ref": 42,
        "options": ["invalid", {"num": True, "value": 123, "use_option": "true"}],
        "exclude": [{"offset": -1, "number_of_addresses": True}],
        "member": {"name": 123, "ipv4addr": ["192.0.2.10"]},
    }
    record = _normalize("rangetemplate", raw)
    assert record.status == "PARTIAL" and record.object_ref is None
    assert record.raw == raw
    assert len(record.options) == 1 and record.options[0].num is None
    assert record.options[0].use_option is None
    assert record.exclude[0].offset is None and record.exclude[0].number_of_addresses is None
    notes = topology_coverage([record])[0]["Notes"]
    assert "options[0]" in notes and "options[1].num" in notes
    assert "exclude[0].offset" in notes and "member.ipv4addr" in notes


def test_invalid_string_array_members_are_reported_without_losing_originals():
    raw = {"option_definitions": ["valid/ref", 17, None]}
    record = _normalize("dhcpoptionspace", raw)
    assert record.option_definitions == ["valid/ref"]
    assert record.raw == raw and record.status == "PARTIAL"
    assert len(record.issues) == 2


@pytest.mark.parametrize("object_type", TOPOLOGY_OBJECTS)
def test_missing_fields_are_unknown_and_empty_headers_remain_useful(object_type):
    record = _normalize(object_type, {})
    assert record.status == "COMPLETE"
    assert record.name is None and record.object_ref is None
    assert record.to_excel()["normalization_status"] == "COMPLETE"
    assert record.to_excel()["data_representation"] == "RAW_CONFIGURATION"
    assert topology_headers(object_type) == list(record.to_excel())
    assert all(value is None for key, value in record.to_excel().items()
               if key not in {"grid", "object_type", "data_representation",
                              "normalization_status", "issues", "extra_fields"})


def test_template_option_rows_are_raw_configuration_without_inheritance_claims():
    result = CollectionResult(grid="SYNTHETIC", records=deepcopy(SYNTHETIC_POPULATED_ROWS))
    # Any accidental effective records must not change the stored template values.
    result.effective_records["networktemplate"] = [{"name": "synthetic-network",
                                                   "options": [{"num": 51, "value": "28800"}]}]
    records = normalize_topology(result)
    rows = topology_option_rows(records)
    assert len(rows) == 2
    assert rows[0]["stored_value"] == "43200"
    assert rows[0]["use_options"] is False and rows[0]["use_option"] is True
    assert rows[1]["stored_value"] == "192.0.2.1" and rows[1]["use_option"] is False
    assert all("effective_value" not in row and "inherited" not in row for row in rows)
    assert all(row["data_representation"] == "RAW_CONFIGURATION" for row in rows)
    assert rows[0]["object_ref"] == result.records["networktemplate"][0]["_ref"]


def test_excel_rows_are_json_types_and_do_not_expose_mutable_record_data():
    records = normalize_topology(CollectionResult(grid="SYNTHETIC", records=SYNTHETIC_POPULATED_ROWS))
    rows = topology_excel_rows(records)
    assert set(rows) == set(TOPOLOGY_SHEETS)
    assert json.loads(json.dumps(rows)) == rows
    network_row = rows["networktemplate"][0]
    assert network_row["members"][0]["name"] == "synthetic-primary.example"
    assert network_row["options"][0]["value"] == "43200"
    network_row["members"][0]["name"] = "edited"
    assert records[1].members[0].name == "synthetic-primary.example"
    assert len(topology_coverage(records)) == 6
    assert all(row["Collection Status"] == "COMPLETE" for row in topology_coverage(records))


def test_no_unrequested_objects_or_effective_only_objects_are_normalized():
    result = CollectionResult(grid="SYNTHETIC", records={"fixedaddress": [{"ipv4addr": "192.0.2.4"}],
                                                       "network": [{"network": "192.0.2.0/24"}]},
                              effective_records={"rangetemplate": [{"name": "effective-only"}]})
    assert normalize_topology(result) == []
    assert topology_option_rows([]) == []
    assert topology_coverage([]) == []
    assert topology_excel_rows([]) == {key: [] for key in TOPOLOGY_SHEETS}


def _schema_sample(field):
    """Generate explicitly synthetic test data using the captured schema types."""
    if "schema" in field:
        value = {child["name"]: _schema_sample(child) for child in field["schema"]["fields"]}
    elif field["type"] == ["bool"]:
        value = False
    elif field["type"] in (["uint"], ["int"]):
        value = 0
    elif "enum_values" in field:
        value = field["enum_values"][0]
    else:
        value = "synthetic-value"
    return [value] if field["is_array"] else value


@pytest.mark.parametrize("object_type", TOPOLOGY_OBJECTS)
def test_all_selected_schema_fields_and_override_flags_have_typed_storage(object_type):
    schema = json.loads((SCHEMAS / f"{object_type}.json").read_text(encoding="utf-8"))
    discovered = {field["name"]: field for field in schema["fields"]}
    selected = set(TOPOLOGY_OBJECTS[object_type][2])
    selected.update(discovered[name]["overridden_by"] for name in list(selected)
                    if "overridden_by" in discovered[name])
    assert all("r" in discovered[name]["supports"] for name in selected)
    assert schema["version"] == "2.13.7"
    raw = {name: _schema_sample(discovered[name]) for name in selected}
    record = _normalize(object_type, raw)
    assert record.status == "COMPLETE", record.issues
    assert record.extra_fields == {}
    assert not selected - set(record.to_excel())
    assert record.raw == raw
    # The report's WAPI fields match precisely the collector/schema selection.
    metadata = {"grid", "object_type", "object_ref", "data_representation",
                "normalization_status", "issues", "extra_fields"}
    assert set(record.to_excel()) - metadata == selected

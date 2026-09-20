"""Synthetic populated examples only for the eleven confirmed-empty LAB types.

The real WAPI 2.13.7 captures are in reservations_lab_20260920. These examples
test response shapes and conservative interpretation, not live object presence.
Superhostchild has no synthetic populated fixture: its live query returned 400.
"""

from copy import deepcopy
from dataclasses import fields
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from infoblox_inventory.models import CollectionResult
from infoblox_inventory.reservations import (
    AssociatedObject, CloudInfo, FixedAddressRecord, HostIPv4Data, HostIPv4Record,
    LogicFilterRule, MSDHCPOption, RESERVATION_SHEETS, normalize_reservations,
    reservation_coverage, reservation_excel_rows, reservation_headers,
    reservation_option_rows, reservation_relationship_rows,
)
from infoblox_inventory.topology import DHCPOption, MemberAssociation, MSServerAssociation


SCHEMAS = Path(__file__).parent / "fixtures" / "reservations_lab_20260920" / "schemas"
SYNTHETIC_POPULATED_ROWS = {
    "fixedaddress": [{
        "_ref": "fixedaddress/synthetic:192.0.2.10/default", "ipv4addr": "192.0.2.10",
        "name": "synthetic-printer", "mac": "00:00:5e:00:53:01",
        "dhcp_client_identifier": "client-identifier", "client_identifier_prepend_zero": False,
        "network": "192.0.2.0/24", "network_view": "default", "match_client": "MAC_ADDRESS",
        "agent_circuit_id": "", "agent_remote_id": "", "enable_ddns": False,
        "ddns_hostname": "synthetic-printer", "ddns_domainname": "example.test",
        "use_enable_ddns": False, "use_ddns_domainname": False,
        "options": [{"name": "routers", "num": 3, "value": "192.0.2.1",
                     "vendor_class": "DHCP", "use_option": True}], "use_options": False,
        "ms_options": [{"name": "routers", "num": 3, "value": "192.0.2.2",
                        "vendor_class": "", "user_class": "", "type": "string"}],
        "use_ms_options": False, "ms_server": {"ipv4addr": "192.0.2.20"},
        "cloud_info": {"delegated_member": {"name": "member.example.test",
                                              "ipv4addr": "192.0.2.30", "ipv6addr": ""},
                       "delegated_scope": "NONE", "delegated_root": "",
                       "owned_by_adaptor": False, "usage": "NONE", "tenant": "",
                       "mgmt_platform": "", "authority_type": "GM"},
        "comment": "Synthetic empty-LAB shape test", "extattrs": {"Owner": {"value": "Test"}},
        "disable": False, "is_invalid_mac": False, "reserved_interface": "",
        "logic_filter_rules": [{"filter": "Corporate", "type": "MAC"}],
        "use_logic_filter_rules": False, "ignore_dhcp_option_list_request": False,
        "use_ignore_dhcp_option_list_request": False, "bootfile": "boot.efi",
        "bootserver": "192.0.2.40", "nextserver": "192.0.2.41", "deny_bootp": False,
        "enable_pxe_lease_time": False, "pxe_lease_time": 600, "use_bootfile": False,
        "use_bootserver": False, "use_nextserver": False, "use_deny_bootp": False,
        "use_pxe_lease_time": False,
    }],
    "record:host": [{
        "_ref": "record:host/synthetic:host.example.test", "name": "host.example.test",
        "network_view": "default", "disable": False, "comment": "Synthetic DHCP host",
        "extattrs": {}, "ipv4addrs": [{
            "_ref": "record:host_ipv4addr/synthetic:192.0.2.11", "ipv4addr": "192.0.2.11",
            "mac": "00:00:5e:00:53:02", "host": "host.example.test",
            "configure_for_dhcp": True, "options": [{"num": 51, "value": "3600"}],
            "use_options": False,
            "logic_filter_rules": [{"filter": "Corporate", "type": "MAC"}],
            "use_logic_filter_rules": True,
        }],
    }],
    "record:host_ipv4addr": [{
        "_ref": "record:host_ipv4addr/synthetic:192.0.2.11", "ipv4addr": "192.0.2.11",
        "mac": "00:00:5e:00:53:02", "host": "host.example.test",
        "network": "192.0.2.0/24", "network_view": "default", "configure_for_dhcp": True,
        "match_client": "MAC_ADDRESS", "options": [], "logic_filter_rules": [],
        "is_invalid_mac": False, "reserved_interface": "",
        "ignore_client_requested_options": False, "use_ignore_client_requested_options": False,
        "use_options": False, "use_logic_filter_rules": False,
    }],
    "roaminghost": [{
        "_ref": "roaminghost/synthetic:roaming", "name": "synthetic-roaming", "address_type": "BOTH",
        "mac": "00:00:5e:00:53:03", "dhcp_client_identifier": "client",
        "client_identifier_prepend_zero": True, "match_client": "CLIENT_ID",
        "network_view": "default", "enable_ddns": False, "ddns_hostname": "roaming",
        "ddns_domainname": "example.test", "force_roaming_hostname": False,
        "options": [{"num": 51, "value": "3600"}], "comment": "Synthetic roaming context",
        "extattrs": {}, "disable": False, "ignore_dhcp_option_list_request": False,
        "ipv6_duid": "00:03:00:01:00:00:5e:00:53:03", "ipv6_mac_address": "00:00:5e:00:53:03",
        "ipv6_match_option": "DUID", "ipv6_options": [{"num": 23, "value": "2001:db8::53"}],
        "preferred_lifetime": 3600, "valid_lifetime": 7200, "use_ipv6_options": False,
        "use_preferred_lifetime": False, "use_valid_lifetime": True,
    }],
    "superhost": [{
        "_ref": "superhost/synthetic:super", "name": "synthetic-super", "comment": "Synthetic links",
        "disabled": False, "dhcp_associated_objects": [
            "fixedaddress/synthetic:192.0.2.10/default",
            {"_ref": "record:host/synthetic:host.example.test", "name": "host.example.test",
             "ipv4addrs": [{"ipv4addr": "192.0.2.11", "configure_for_dhcp": True}]},
        ],
    }],
    "filtermac": [{
        "_ref": "filtermac/synthetic:Corporate", "name": "Corporate",
        "comment": "Name has no policy meaning", "disable": False,
        "default_mac_address_expiration": 3600, "enforce_expiration_times": True,
        "never_expires": False, "lease_time": 3600,
        "options": [{"num": 51, "value": "3600", "use_option": False}],
    }],
    "macfilteraddress": [{
        "_ref": "macfilteraddress/synthetic:Corporate/00:00:5e:00:53:01",
        "mac": "00:00:5e:00:53:01", "filter": "Corporate", "comment": "Synthetic entry",
        "authentication_time": 1750000000, "expiration_time": 1760000000,
        "never_expires": False, "fingerprint": "Example fingerprint", "is_registered_user": False,
    }],
    "filteroption": [{
        "_ref": "filteroption/synthetic:Allowed", "name": "Allowed", "comment": "Opaque expression",
        "expression": 'option vendor-class-identifier = "synthetic"', "apply_as_class": False,
        "option_space": "DHCP", "option_list": [{"num": 51, "value": "1200"}],
        "lease_time": 1200, "bootfile": "boot.efi", "bootserver": "192.0.2.40",
        "next_server": "192.0.2.41", "pxe_lease_time": 600,
    }],
    "filterrelayagent": [{
        "_ref": "filterrelayagent/synthetic:relay", "name": "relay", "comment": "Synthetic relay",
        "is_circuit_id": "MATCHES_VALUE", "circuit_id_name": "circuit-data",
        "is_circuit_id_substring": True, "circuit_id_substring_offset": 0,
        "circuit_id_substring_length": 4, "is_remote_id": "ANY", "remote_id_name": "",
        "is_remote_id_substring": False, "remote_id_substring_offset": 0,
        "remote_id_substring_length": 0,
    }],
    "filterfingerprint": [{
        "_ref": "filterfingerprint/synthetic:fingerprints", "name": "fingerprints",
        "comment": "Synthetic fingerprint strings", "fingerprint": ["Example A", "Example B"],
    }],
    "filternac": [{
        "_ref": "filternac/synthetic:nac", "name": "nac", "comment": "Opaque NAC expression",
        "expression": "synthetic-nac-expression", "lease_time": 600,
        "options": [{"num": 51, "value": "600"}],
    }],
}


def normalize_one(object_type, row):
    return normalize_reservations(CollectionResult(grid="Synthetic", records={object_type: [row]}))[0]


@pytest.mark.parametrize("object_type", SYNTHETIC_POPULATED_ROWS)
def test_confirmed_empty_objects_have_typed_synthetic_examples_matching_schema(object_type):
    row = SYNTHETIC_POPULATED_ROWS[object_type][0]
    schema = json.loads((SCHEMAS / (quote(object_type, safe="") + ".json")).read_text())
    schema_fields = {item["name"]: item for item in schema["fields"]}
    assert set(row) - {"_ref"} <= schema_fields.keys()
    for name, value in row.items():
        if name != "_ref" and "enum_values" in schema_fields[name]:
            assert value in schema_fields[name]["enum_values"]
    record = normalize_one(object_type, row)
    assert record.status == "COMPLETE", record.issues
    assert record.raw == row
    assert record.extra_fields == {}
    assert record.object_type == object_type
    assert record.to_excel()["data_representation"] == "RAW_CONFIGURATION"


def test_fixed_address_nested_types_and_use_flags_remain_stored_configuration():
    record = normalize_one("fixedaddress", SYNTHETIC_POPULATED_ROWS["fixedaddress"][0])
    assert isinstance(record, FixedAddressRecord)
    assert isinstance(record.options[0], DHCPOption)
    assert isinstance(record.ms_options[0], MSDHCPOption)
    assert isinstance(record.ms_server, MSServerAssociation)
    assert isinstance(record.cloud_info, CloudInfo)
    assert isinstance(record.cloud_info.delegated_member, MemberAssociation)
    assert isinstance(record.logic_filter_rules[0], LogicFilterRule)
    assert record.options[0].value == "192.0.2.1"
    assert record.use_options is False
    assert record.extattrs == {"Owner": {"value": "Test"}}
    assert not hasattr(record, "effective_value")


def test_full_raw_unknown_and_nested_values_are_independent_deep_copies():
    row = deepcopy(SYNTHETIC_POPULATED_ROWS["fixedaddress"][0])
    row["future"] = {"items": [1]}
    row["options"][0]["future_option"] = {"items": [2]}
    row["cloud_info"]["delegated_member"]["future_member"] = [3]
    record = normalize_one("fixedaddress", row)
    row["future"]["items"].append(9)
    row["options"][0]["future_option"]["items"].append(9)
    row["cloud_info"]["delegated_member"]["future_member"].append(9)
    assert record.raw["future"] == {"items": [1]}
    assert record.extra_fields["future"] == {"items": [1]}
    assert record.options[0].raw["future_option"] == {"items": [2]}
    assert record.options[0].extra_fields["future_option"] == {"items": [2]}
    assert record.cloud_info.delegated_member.extra_fields["future_member"] == [3]
    record.raw["future"]["items"].append(8)
    assert record.extra_fields["future"] == {"items": [1]}


@pytest.mark.parametrize("object_type,field,value,path", [
    ("fixedaddress", "disable", "false", "disable"),
    ("fixedaddress", "pxe_lease_time", True, "pxe_lease_time"),
    ("fixedaddress", "pxe_lease_time", -1, "pxe_lease_time"),
    ("fixedaddress", "options", [{"num": "3"}], "options[0].num"),
    ("fixedaddress", "options", [None], "options[0]"),
    ("fixedaddress", "ms_options", [{"value": 3}], "ms_options[0].value"),
    ("fixedaddress", "logic_filter_rules", [{"filter": False}], "logic_filter_rules[0].filter"),
    ("fixedaddress", "cloud_info", {"delegated_member": {"name": 4}}, "cloud_info.delegated_member.name"),
    ("fixedaddress", "ms_server", "192.0.2.20", "ms_server"),
    ("fixedaddress", "extattrs", [], "extattrs"),
    ("filterfingerprint", "fingerprint", "example", "fingerprint"),
    ("filterfingerprint", "fingerprint", [False], "fingerprint[0]"),
    ("filterrelayagent", "is_circuit_id", True, "is_circuit_id"),
    ("macfilteraddress", "authentication_time", "1750000000", "authentication_time"),
    ("superhost", "dhcp_associated_objects", [42], "dhcp_associated_objects[0]"),
    ("record:host", "ipv4addrs", [{"configure_for_dhcp": "true"}], "ipv4addrs[0].configure_for_dhcp"),
])
def test_malformed_fields_have_precise_paths_without_coercion_or_raw_loss(object_type, field, value, path):
    row = deepcopy(SYNTHETIC_POPULATED_ROWS[object_type][0])
    row[field] = value
    record = normalize_one(object_type, row)
    assert record.status == "PARTIAL"
    assert any(issue.startswith(path + ":") for issue in record.issues)
    assert record.raw[field] == value
    coverage = reservation_coverage([record])
    assert coverage[0]["Collection Status"] == "PARTIAL"


def test_missing_optional_values_remain_none_and_effective_records_are_ignored():
    result = CollectionResult(grid="Synthetic", records={"fixedaddress": [{"_ref": "fixedaddress/synthetic"}]},
                              effective_records={"fixedaddress": [{"_ref": "fixedaddress/synthetic",
                                                                     "options": [{"num": 51, "value": "3600"}]}]})
    record = normalize_reservations(result)[0]
    assert record.options is None
    assert record.disable is None
    assert record.status == "COMPLETE"
    assert reservation_option_rows([record]) == []


@pytest.mark.parametrize("value,expected", [(True, "COMPLETE"), (False, "NOT_CONFIGURED"),
                                             (None, "PARTIAL"), ("false", "PARTIAL")])
def test_host_ipv4_dhcp_configuration_uses_only_explicit_boolean(value, expected):
    row = {} if value is None else {"configure_for_dhcp": value}
    record = normalize_one("record:host_ipv4addr", row)
    assert isinstance(record, HostIPv4Record)
    assert record.dhcp_configuration_status == expected
    assert record.to_excel()["dhcp_configuration_status"] == expected
    assert reservation_coverage([record])[1]["Collection Status"] == expected


@pytest.mark.parametrize("addresses,expected", [
    ([], "NOT_CONFIGURED"),
    ([{"configure_for_dhcp": False}], "NOT_CONFIGURED"),
    ([{"configure_for_dhcp": True}, {"configure_for_dhcp": False}], "COMPLETE"),
    ([{}], "PARTIAL"),
    (["record:host_ipv4addr/synthetic"], "PARTIAL"),
    ([{"configure_for_dhcp": True}, "record:host_ipv4addr/synthetic"], "PARTIAL"),
    ([{"configure_for_dhcp": False}, False], "PARTIAL"),
])
def test_host_parent_dhcp_status_never_infers_configuration_from_name_or_reference(addresses, expected):
    record = normalize_one("record:host", {"name": "dhcp-enabled.example.test", "ipv4addrs": addresses})
    assert record.dhcp_configuration_status == expected
    assert reservation_coverage([record])[1]["Collection Status"] == expected


def test_host_embedded_structures_and_superhost_union_references_are_preserved():
    host = normalize_one("record:host", SYNTHETIC_POPULATED_ROWS["record:host"][0])
    assert isinstance(host.ipv4addrs[0], HostIPv4Data)
    assert isinstance(host.ipv4addrs[0].options[0], DHCPOption)
    assert host.ipv4addrs[0].object_ref.startswith("record:host_ipv4addr/")
    superhost = normalize_one("superhost", SYNTHETIC_POPULATED_ROWS["superhost"][0])
    assert isinstance(superhost.dhcp_associated_objects[0], str)
    assert isinstance(superhost.dhcp_associated_objects[1], AssociatedObject)
    embedded = superhost.dhcp_associated_objects[1]
    assert embedded.extra_fields["ipv4addrs"][0]["configure_for_dhcp"] is True
    assert embedded.raw == SYNTHETIC_POPULATED_ROWS["superhost"][0]["dhcp_associated_objects"][1]


def test_options_and_relationship_rows_do_not_infer_policy_or_effective_values():
    records = normalize_reservations(CollectionResult(grid="Synthetic", records=deepcopy(SYNTHETIC_POPULATED_ROWS)))
    rows = reservation_option_rows(records)
    assert {row["option_field"] for row in rows} >= {"options", "option_list", "ms_options",
                                                    "ipv6_options", "ipv4addrs[0].options"}
    fixed = next(row for row in rows if row["object_type"] == "fixedaddress" and row["option_field"] == "options")
    assert fixed["stored_value"] == "192.0.2.1"
    assert fixed["use_options"] is False
    assert all("effective_value" not in row and "policy_action" not in row for row in rows)
    relations = reservation_relationship_rows(records)
    corporate = [row for row in relations if row["target"] == "Corporate"]
    assert corporate
    assert {row["relationship_field"] for row in corporate} >= {"filter", "logic_filter_rules"}
    assert all(row["data_representation"] == "RAW_CONFIGURATION" for row in relations)
    assert all("permitted" not in row and "denied" not in row for row in relations)
    assert next(row for row in corporate if row["object_type"] == "fixedaddress")["use_logic_filter_rules"] is False


def test_exported_option_and_rule_paths_keep_raw_indexes_after_malformed_items():
    raw = {
        "ipv4addrs": [42, {
            "configure_for_dhcp": True,
            "options": [False, {"num": 3, "value": "192.0.2.1"}],
            "logic_filter_rules": [None, {"filter": "Corporate", "type": "MAC"}],
        }],
    }
    record = normalize_one("record:host", raw)
    assert record.status == "PARTIAL"
    assert record.raw == raw
    option = reservation_option_rows([record])[0]
    assert option["option_field"] == "ipv4addrs[1].options"
    assert option["option_index"] == 1
    relationships = reservation_relationship_rows([record])
    assert relationships[0]["relationship_field"] == "ipv4addrs"
    assert relationships[0]["relationship_index"] == 1
    assert relationships[1]["relationship_field"] == "ipv4addrs[1].logic_filter_rules"
    assert relationships[1]["relationship_index"] == 1
    assert "ipv4addrs[1].options[0]:" in " ".join(record.issues)


def test_duplicate_reference_and_embedded_relationship_indexes_are_not_deduplicated():
    reference = "fixedaddress/synthetic:192.0.2.10/default"
    embedded = {"_ref": "record:host/synthetic:host.example.test", "name": "host.example.test"}
    raw = {"dhcp_associated_objects": [False, reference, reference, 42, embedded, embedded]}
    record = normalize_one("superhost", raw)
    rows = reservation_relationship_rows([record])
    assert [row["relationship_index"] for row in rows] == [1, 2, 4, 5]
    assert [row["relationship_data"] for row in rows] == [reference, reference, embedded, embedded]
    assert record.raw == raw


def test_repeated_host_references_and_nested_options_preserve_all_raw_positions():
    reference = "record:host_ipv4addr/synthetic:192.0.2.11"
    option = {"num": 51, "value": "3600"}
    embedded = {"configure_for_dhcp": True, "options": [False, option, option]}
    raw = {"ipv4addrs": [reference, None, reference, embedded, embedded]}
    record = normalize_one("record:host", raw)
    rows = reservation_relationship_rows([record])
    assert [row["relationship_index"] for row in rows] == [0, 2, 3, 4]
    options = reservation_option_rows([record])
    assert [(row["option_field"], row["option_index"]) for row in options] == [
        ("ipv4addrs[3].options", 1), ("ipv4addrs[3].options", 2),
        ("ipv4addrs[4].options", 1), ("ipv4addrs[4].options", 2),
    ]


def test_fixed_address_top_level_options_and_rules_keep_raw_indexes():
    record = normalize_one("fixedaddress", {
        "options": [None, {"num": 3, "value": "192.0.2.1"}],
        "ms_options": [False, {"num": 3, "value": "192.0.2.2"}],
        "logic_filter_rules": [42, {"filter": "Corporate", "type": "MAC"}],
    })
    assert [row["option_index"] for row in reservation_option_rows([record])] == [1, 1]
    assert reservation_relationship_rows([record])[0]["relationship_index"] == 1


def test_host_configuration_coverage_is_explicitly_ipv4_only():
    record = normalize_one("record:host", {"ipv4addrs": []})
    coverage = reservation_coverage([record])[1]
    assert coverage["Collection Status"] == "NOT_CONFIGURED"
    assert "IPv4 only" in coverage["Notes"]
    assert "DHCPv6 configuration is not assessed" in coverage["Notes"]


def test_empty_results_preserve_collection_coverage_without_fabricating_normalized_records():
    result = CollectionResult(grid="Synthetic", records={key: [] for key in RESERVATION_SHEETS},
                              coverage=[{"Object": "fixedaddress", "Collection Status": "EMPTY"}])
    before = deepcopy(result)
    records = normalize_reservations(result)
    assert records == []
    assert reservation_coverage(records) == []
    assert reservation_option_rows(records) == []
    assert reservation_relationship_rows(records) == []
    assert result == before
    assert set(reservation_excel_rows(records)) == set(RESERVATION_SHEETS)
    for object_type in RESERVATION_SHEETS:
        assert {"grid", "object_ref", "normalization_status", "extra_fields"} <= set(reservation_headers(object_type))


def test_roaming_host_does_not_claim_a_fixed_ip_and_relay_modes_are_strings():
    roaming = normalize_one("roaminghost", SYNTHETIC_POPULATED_ROWS["roaminghost"][0])
    assert "ipv4addr" not in roaming.to_excel()
    assert roaming.address_type == "BOTH"
    relay = normalize_one("filterrelayagent", SYNTHETIC_POPULATED_ROWS["filterrelayagent"][0])
    assert relay.is_circuit_id == "MATCHES_VALUE"
    assert relay.is_remote_id == "ANY"
    assert relay.is_circuit_id_substring is True


def test_dataclass_fields_and_excel_headers_cover_selected_readable_schema_fields():
    from infoblox_inventory.collectors.reservations import RESERVATION_OBJECTS

    for object_type, (_, _, selected) in RESERVATION_OBJECTS.items():
        record = normalize_one(object_type, {})
        dataclass_fields = {item.name for item in fields(record)}
        assert set(selected) <= dataclass_fields
        assert set(selected) <= set(reservation_headers(object_type))
        schema = json.loads((SCHEMAS / (quote(object_type, safe="") + ".json")).read_text())
        overrides = {item["overridden_by"] for item in schema["fields"]
                     if item["name"] in selected and item.get("overridden_by")}
        assert overrides <= dataclass_fields

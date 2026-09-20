from copy import deepcopy
import json
from pathlib import Path

import pytest

from infoblox_inventory.normalize import normalize_options, normalize_scalars, parse_source_ref


FIXTURES = Path(__file__).parent / "fixtures"
EMPIRICAL = json.loads((FIXTURES / "empirical_inheritance.json").read_text(encoding="utf-8"))


def test_raw_shadow_lease_is_never_used_as_effective_value():
    rows = normalize_options("LAB-GRID", "https://grid", "2.13.7", EMPIRICAL["records"],
                             EMPIRICAL["effective_records"], EMPIRICAL["schemas"])
    row = next(row for row in rows if row["object_type"] == "member:dhcpproperties")
    assert row["raw_value"] == "43200"
    assert row["raw_use"] is False
    assert row["raw_use_option"] is False
    assert row["effective_value"] == "28800"
    assert row["configured_here"] is False
    assert row["source_level"] == "Grid"
    assert row["status"] == "COMPLETE"


def test_options_use_outer_groups_and_preserve_all_four_effective_sources():
    rows = normalize_options("LAB-GRID", "https://grid", "2.13.7", EMPIRICAL["records"],
                             EMPIRICAL["effective_records"], EMPIRICAL["schemas"])
    by_name = {row["parameter"]: row for row in rows if row["object_type"] == "range"}
    assert len(by_name) == 4
    assert {name: row["source_level"] for name, row in by_name.items()} == {
        "dhcp-lease-time": "Range", "routers": "Network", "domain-name-servers": "Member", "domain-name": "Grid",
    }
    local = by_name["dhcp-lease-time"]
    assert local["configured_here"] is True
    assert local["source_ref"] == local["object_ref"]
    assert local["source_object"] == "10.77.10.100-10.77.10.199"
    routers = by_name["routers"]
    assert routers["effective_value"] == "10.77.10.1"
    assert routers["inherited"] is True
    assert routers["configured_here"] is False
    assert routers["source_object"] == "10.77.10.0/24"
    assert routers["source_network_view"] == "default"
    assert routers["inheritance_details"]["values"][0]["use_option"] is False
    assert all(row["parent_network"] == "10.77.10.0/24" for row in by_name.values())


@pytest.mark.parametrize("case", EMPIRICAL["scalar_cases"], ids=lambda case: case["description"])
def test_scalar_empirical_cases(case):
    object_type, field = case["object_type"], case["field"]
    raw = {object_type: [{"_ref": case["ref"], field: "shadow/default", "override_toggle": False}]}
    effective = {object_type: [{"_ref": case["ref"], field: case["wrapper"]}]}
    schemas = {object_type: {"fields": [{"name": field, "overridden_by": "override_toggle"}]}}
    row, = normalize_scalars("LAB-GRID", "https://grid", "2.13.7", raw, effective, schemas)
    assert row["effective_value"] == case["expected_value"]
    assert row["source_level"] == case["expected_level"]
    assert row["source_object"] == case["expected_object"]
    assert row["status"] == case["expected_status"]
    assert row["raw_value"] == "shadow/default"
    assert row["raw_use_field"] == "override_toggle"
    assert row["raw_use"] is False
    assert row["inheritance_details"] == case["wrapper"]
    assert row["source_ref"] == (case["ref"] if case["wrapper"]["inherited"] is False else case["wrapper"]["source"])


def test_raw_and_unwrapped_child_scalars_remain_unresolved():
    raw = {"network": [{"_ref": "network/1", "custom_boot_parameter": "shadow", "override_toggle": True,
                         "unrelated_value": "not inherited simply because metadata is absent"}]}
    schema = {"network": {"fields": [{"name": "custom_boot_parameter", "overridden_by": "override_toggle"},
                                     {"name": "unrelated_value"}]}}
    for effective in ({}, deepcopy(raw)):
        row, = normalize_scalars("G", "", "2.13.7", raw, effective, schema)
        assert row["parameter"] == "custom_boot_parameter"
        assert row["effective_value"] is None
        assert row["inherited"] is None
        assert row["configured_here"] is None
        assert row["status"] == "PARTIAL"


def test_grid_root_values_can_be_reported_as_local_without_override_metadata():
    raw = {"grid:dhcpproperties": [{"_ref": "grid:dhcpproperties/example:LAB-GRID", "nextserver": "10.77.0.10",
                                    "options": [{"name": "domain-name", "num": 15, "value": "lab.local", "use_option": True}]}]}
    scalar, = normalize_scalars("LAB-GRID", "", "2.13.7", raw)
    option, = normalize_options("LAB-GRID", "", "2.13.7", raw)
    assert scalar["effective_value"] == "10.77.0.10"
    assert option["effective_value"] == "lab.local"
    assert scalar["configured_here"] is option["configured_here"] is True
    assert scalar["source_level"] == option["source_level"] == "Grid"


def test_grid_root_option_marked_unused_is_not_promoted():
    raw = {"grid:dhcpproperties": [{"_ref": "grid:dhcpproperties/example:LAB-GRID",
                                    "options": [{"name": "domain-name", "value": "shadow", "use_option": False}]}]}
    option, = normalize_options("LAB-GRID", "", "2.13.7", raw)
    assert option["effective_value"] is None
    assert option["status"] == "PARTIAL"


def test_normalization_does_not_mutate_raw_or_effective_evidence():
    evidence = deepcopy(EMPIRICAL)
    before = deepcopy(evidence)
    rows = normalize_options("LAB-GRID", "", "2.13.7", evidence["records"], evidence["effective_records"])
    rows[0]["inheritance_details"]["values"][0]["value"] = "changed normalized output only"
    assert evidence == before


def test_synthetic_multisource_preserves_all_relationships_without_choosing_one():
    wrapper = json.loads((FIXTURES / "synthetic_multisource.json").read_text(encoding="utf-8"))["wrapper"]
    effective = {"network": [{"_ref": "network/example:10.77.10.0/24/default", "nextserver": wrapper}]}
    row, = normalize_scalars("G", "", "2.13.7", {}, effective)
    assert row["multisource"] is True
    assert row["configured_here"] is None
    assert row["source_level"] == "MULTISOURCE"
    assert row["source_ref"] == wrapper["source"]
    assert row["effective_value"] == wrapper["value"]
    assert row["inheritance_details"] == wrapper
    row["inheritance_details"]["source"].append("new")
    assert effective["network"][0]["nextserver"] == wrapper


def test_option_vendor_spaces_are_not_collapsed():
    ref = "network/example:10.77.10.0/24/default"
    effective = {"network": [{"_ref": ref, "options": [{"inherited": False, "source": "", "values": [
        {"name": "custom", "num": 200, "vendor_class": "A", "value": "one", "use_option": False},
        {"name": "custom", "num": 200, "vendor_class": "B", "value": "two", "use_option": False},
    ]}]}]}
    rows = normalize_options("G", "", "2.13.7", {}, effective)
    assert {(row["vendor_class"], row["effective_value"]) for row in rows} == {("A", "one"), ("B", "two")}
    assert all(row["configured_here"] is True for row in rows)


def test_source_ref_parser_retains_unknown_reference():
    source = parse_source_ref("futureobject/opaque-ref")
    assert source["source_ref"] == "futureobject/opaque-ref"
    assert source["source_object"] == ""


@pytest.mark.parametrize("wrapper", [
    {"inherited": True, "source": ["grid:dhcpproperties/example:G"], "value": "10.0.0.1"},
    {"inherited": False, "source": "grid:dhcpproperties/example:G", "value": "10.0.0.1"},
    {"inherited": True, "source": "", "value": "10.0.0.1"},
])
def test_malformed_scalar_provenance_stays_unresolved(wrapper):
    row, = normalize_scalars("G", "", "2.13.7", {}, {"network": [{"_ref": "network/1", "nextserver": wrapper}]})
    assert row["status"] == "PARTIAL"
    assert row["effective_value"] is None
    assert row["configured_here"] is None
    assert row["inheritance_details"] == wrapper


def test_unrecognized_effective_option_shape_is_preserved_as_unresolved():
    group = {"inherited": True, "source": "grid:dhcpproperties/example:G", "values": {"future": "shape"}}
    row, = normalize_options("G", "", "2.13.7", {}, {"range": [{"_ref": "range/1", "options": [group]}]})
    assert row["status"] == "PARTIAL"
    assert row["effective_value"] is None
    assert row["inheritance_details"] == group

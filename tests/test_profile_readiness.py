"""Evidence readiness must remain separate from configuration quality."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from infoblox_inventory.models import CollectionResult
from infoblox_inventory.normalize import normalize_options
from infoblox_inventory.profile_readiness import (
    PROFILE_INPUT_SPECS,
    ProfileInputSpec,
    build_profile_readiness,
    profile_readiness_summary,
    validate_profile_inputs,
)
from infoblox_inventory.standardization import PARAMETER_SPECS, build_standardization


NETWORK_IDS = {
    "dhcp.lease_time.network", "dhcp.dns_servers.network", "dhcp.domain_name.network",
    "dhcp.domain_search.network", "dhcp.router.network", "dhcp.ntp_servers.network",
    "dhcp.deny_bootp.network", "ddns.enabled.network", "ddns.domain.network",
    "ddns.generate_hostname.network", "ddns.ttl.network", "ddns.update_fixed_addresses.network",
    "ddns.use_option81.network", "ddns.update_on_renewal.network", "pxe.nextserver.network",
    "pxe.bootserver.network", "pxe.bootfile.network", "pxe.tftp_server_name.network",
    "pxe.bootfile_name_option.network", "pxe.lease_time.network", "pxe.lease_enabled.network",
}
RANGE_IDS = {
    "dhcp.lease_time.range", "dhcp.dns_servers.range", "dhcp.domain_name.range",
    "dhcp.domain_search.range", "dhcp.router.range", "dhcp.ntp_servers.range",
    "dhcp.deny_bootp.range", "ddns.enabled.range", "ddns.domain.range",
    "ddns.generate_hostname.range", "ddns.update_on_renewal.range", "pxe.nextserver.range",
    "pxe.bootserver.range", "pxe.bootfile.range", "pxe.tftp_server_name.range",
    "pxe.bootfile_name_option.range", "pxe.lease_time.range", "pxe.lease_enabled.range",
}
HEADERS = [
    "Profile", "Input Key", "Input", "Semantic Role", "Parameter ID", "Scope",
    "Population Basis", "Source Population Objects",
    "Required Field", "Required Field Status", "Population Objects", "Query Evidence Objects",
    "Query Coverage %", "Collection Status", "Confirmed Objects", "Confirmed Value %",
    "Explicit Not Configured", "Resolved Evidence %", "Unresolved Objects", "Unresolved %",
    "Evidence Status", "Readiness", "Readiness Reason",
]
EVIDENCE_HEADERS = HEADERS[8:21]


def _spec(parameter_id="pxe.bootserver.network"):
    return next(item for item in PROFILE_INPUT_SPECS if item.source_parameter_id == parameter_id)


def _evidence(parameter_id="pxe.bootserver.network", *, population=130, confirmed=127,
              not_configured=3, collection="COMPLETE", evidence="COMPLETE"):
    resolved = confirmed + not_configured
    parameter = next(item for item in PARAMETER_SPECS if item.key == parameter_id)
    return {
        "Parameter ID": parameter_id,
        "Scope": parameter.scope,
        "Required Field": parameter.required_field,
        "Required Field Status": "AVAILABLE_OR_NOT_FLAGGED",
        "Population Objects": population,
        "Query Evidence Objects": population,
        "Query Coverage %": 100.0 if population else None,
        "Collection Status": collection,
        "Confirmed Objects": confirmed,
        "Confirmed Value %": round(confirmed * 100.0 / population, 1) if population else None,
        "Explicit Not Configured": not_configured,
        "Resolved Evidence %": round(resolved * 100.0 / population, 1) if population else None,
        "Unresolved Objects": population - resolved,
        "Unresolved %": round((population - resolved) * 100.0 / population, 1) if population else None,
        "Evidence Status": evidence,
    }


def _one(evidence):
    return build_profile_readiness([evidence], (_spec(evidence["Parameter ID"]),))[0]


def _coverage(object_type, count, query="effective", status="COMPLETE"):
    return {
        "Grid": "LAB", "Object": object_type, "Query": query, "Field": "",
        "Collection Status": status, "Objects Found": count,
    }


def _collection(networks=0, ranges=0):
    records = {
        "network": [{"_ref": f"network/LAB/{i}"} for i in range(networks)],
        "range": [{"_ref": f"range/LAB/{i}"} for i in range(ranges)],
    }
    return CollectionResult(
        grid="LAB", records=records, effective_records=deepcopy(records),
        coverage=[_coverage(kind, len(rows), query) for kind, rows in records.items()
                  for query in ("raw", "effective")],
    )


def _scalar(kind, index, *, status="COMPLETE"):
    return {
        "grid": "LAB", "object_type": kind, "object_ref": f"{kind}/LAB/{index}",
        "object_name": f"{kind}-{index}", "network_view": "default", "parent_network": "",
        "parameter": "bootserver", "effective_value": "192.0.2.10" if status == "COMPLETE" else None,
        "configured_here": False, "inherited": True, "multisource": False,
        "source_level": "Grid" if status == "COMPLETE" else "NOT_DEFINED",
        "source_object": "LAB", "source_ref": "grid:dhcpproperties/LAB", "status": status,
    }


def _from_normalized(result, rows):
    standardization = build_standardization([result], result.coverage, rows, [], {})
    return build_profile_readiness(standardization)


def _find(rows, parameter_id):
    return next(row for row in rows if row["Parameter ID"] == parameter_id)


def test_candidate_sets_match_supported_network_and_range_parameters_exactly():
    validate_profile_inputs()
    by_profile = {
        profile: {item.source_parameter_id for item in PROFILE_INPUT_SPECS if item.profile == profile}
        for profile in {item.profile for item in PROFILE_INPUT_SPECS}
    }
    assert by_profile == {"Network Profile v1": NETWORK_IDS, "Range Profile v1": RANGE_IDS}
    assert len(PROFILE_INPUT_SPECS) == 39
    assert len(NETWORK_IDS) == 21
    assert len(RANGE_IDS) == 18
    actual_parameters = {item.key: item for item in PARAMETER_SPECS}
    for item in PROFILE_INPUT_SPECS:
        assert item.scope == actual_parameters[item.source_parameter_id].scope
        assert item.scope in {"Network", "Range"}
        assert item.label


def test_gateway_is_marked_for_later_derivation_without_transforming_evidence():
    for scope in ("network", "range"):
        item = _spec(f"dhcp.router.{scope}")
        assert item.input_key == "gateway_convention"
        assert item.semantic_role == "DERIVED_LATER"
    for scope in ("network", "range"):
        item = _spec(f"pxe.lease_enabled.{scope}")
        assert item.semantic_role == "COMPOSITE_LATER"
    assert all(item.semantic_role == "DIRECT" for item in PROFILE_INPUT_SPECS
               if not item.source_parameter_id.startswith("dhcp.router.")
               and not item.source_parameter_id.startswith("pxe.lease_enabled."))


def test_profile_input_spec_is_immutable():
    with pytest.raises(FrozenInstanceError):
        _spec().scope = "Range"


def test_profile_input_model_defaults_to_direct_semantics():
    item = ProfileInputSpec("Network Profile v1", "example", "Example",
                            "pxe.bootserver.network", "Network")
    assert item.semantic_role == "DIRECT"


def test_composite_later_input_is_deferred_and_excluded_from_applicable_rate():
    spec = _spec("pxe.lease_enabled.network")
    row = build_profile_readiness([_evidence(spec.source_parameter_id)], (spec,))[0]
    assert row["Readiness"] == "DEFERRED"
    assert "composite" in row["Readiness Reason"].lower()
    summary = profile_readiness_summary([row])[0]
    assert summary["Candidate Inputs"] == 1
    assert summary["Applicable Inputs"] == 0
    assert summary["DEFERRED"] == 1
    assert summary["Ready Input %"] is None


def test_127_confirmed_plus_three_explicit_not_configured_are_fully_ready():
    evidence = _evidence()
    row = _one(evidence)
    assert row["Readiness"] == "READY"
    assert row["Resolved Evidence %"] == 100.0
    assert row["Confirmed Value %"] == 97.7
    assert "130/130 resolved evidence (100.00% exact)" in row["Readiness Reason"]
    assert list(row) == HEADERS
    assert {key: row[key] for key in EVIDENCE_HEADERS} == {
        key: evidence[key] for key in EVIDENCE_HEADERS
    }


def test_complete_collection_with_three_unresolved_objects_is_still_ready():
    row = _one(_evidence(not_configured=0, evidence="PARTIAL"))
    assert row["Readiness"] == "READY"
    assert row["Resolved Evidence %"] == 97.7
    assert row["Unresolved Objects"] == 3
    assert row["Collection Status"] == "COMPLETE"
    assert "127/130 resolved evidence (97.69% exact)" in row["Readiness Reason"]
    assert "3/130" in row["Readiness Reason"]
    assert "unresolved" in row["Readiness Reason"].lower()


@pytest.mark.parametrize(("confirmed", "expected"), [
    (1000, "READY"), (950, "READY"), (949, "CONDITIONAL"), (900, "CONDITIONAL"),
    (800, "CONDITIONAL"), (799, "NOT_READY"), (0, "NOT_READY"),
])
def test_resolved_evidence_threshold_boundaries(confirmed, expected):
    row = _one(_evidence(population=1000, confirmed=confirmed, not_configured=0,
                         evidence="PARTIAL" if confirmed < 1000 else "COMPLETE"))
    assert row["Readiness"] == expected
    assert f"{confirmed}/1000 resolved evidence ({confirmed / 10:.2f}% exact)" in row["Readiness Reason"]


def test_130_objects_with_90_percent_resolved_are_conditional():
    row = _one(_evidence(confirmed=117, not_configured=0, evidence="PARTIAL"))
    assert row["Resolved Evidence %"] == 90.0
    assert row["Readiness"] == "CONDITIONAL"


def test_rounded_95_percent_display_does_not_promote_9495_percent_to_ready():
    evidence = _evidence(population=2000, confirmed=1899, not_configured=0, evidence="PARTIAL")
    assert evidence["Resolved Evidence %"] == 95.0
    row = _one(evidence)
    assert row["Readiness"] == "CONDITIONAL"
    assert "1899/2000 resolved evidence (94.95% exact)" in row["Readiness Reason"]


def test_exact_95_percent_boundary_is_ready():
    evidence = _evidence(population=2000, confirmed=1900, not_configured=0, evidence="PARTIAL")
    assert evidence["Resolved Evidence %"] == 95.0
    row = _one(evidence)
    assert row["Readiness"] == "READY"


@pytest.mark.parametrize(("field", "status", "reason_hint"), [
    ("Collection Status", "ERROR", "error"),
    ("Collection Status", "PARTIAL", "partial"),
    ("Collection Status", "UNKNOWN", "unknown"),
    ("Required Field Status", "NOT_EXPOSED_BY_WAPI", "field"),
    ("Evidence Status", "ERROR", "error"),
    ("Evidence Status", "NOT_EXPOSED_BY_WAPI", "exposed"),
    ("Evidence Status", "INSUFFICIENT_DATA", "insufficient"),
])
def test_hard_blockers_override_99_percent_resolved_evidence(field, status, reason_hint):
    evidence = _evidence(population=100, confirmed=99, not_configured=0)
    evidence[field] = status
    row = _one(evidence)
    assert row["Readiness"] == "NOT_READY"
    assert row["Resolved Evidence %"] == 99.0
    assert reason_hint in row["Readiness Reason"].lower()


@pytest.mark.parametrize("collection", ["COMPLETE", "EMPTY"])
def test_zero_population_is_not_applicable_only_when_collection_confirms_empty_scope(collection):
    evidence = _evidence(population=0, confirmed=0, not_configured=0,
                         collection=collection, evidence="ERROR")
    row = _one(evidence)
    assert row["Readiness"] == "NOT_APPLICABLE"
    assert row["Resolved Evidence %"] is None
    assert "no objects" in row["Readiness Reason"].lower()


@pytest.mark.parametrize("collection", ["PARTIAL", "ERROR", "UNKNOWN"])
def test_zero_population_after_incomplete_collection_is_not_ready(collection):
    evidence = _evidence(population=0, confirmed=0, not_configured=0,
                         collection=collection, evidence="ERROR")
    row = _one(evidence)
    assert row["Readiness"] == "NOT_READY"
    assert row["Resolved Evidence %"] is None
    assert "population could not be established" in row["Readiness Reason"].lower()
    assert collection.lower() in row["Readiness Reason"].lower()


@pytest.mark.parametrize(("field", "value"), [
    ("Population Objects", None), ("Population Objects", -1), ("Population Objects", True),
    ("Population Objects", float("nan")), ("Population Objects", float("inf")),
    ("Resolved Evidence %", None), ("Resolved Evidence %", -0.1),
    ("Resolved Evidence %", 100.1), ("Resolved Evidence %", True),
    ("Resolved Evidence %", float("nan")), ("Resolved Evidence %", float("inf")),
    ("Resolved Evidence %", "100"),
    ("Collection Status", "FUTURE_UNKNOWN_STATUS"),
    ("Evidence Status", "FUTURE_UNKNOWN_STATUS"),
    ("Required Field Status", "FUTURE_UNKNOWN_STATUS"),
])
def test_invalid_or_unknown_metrics_cannot_be_ready(field, value):
    evidence = _evidence()
    evidence[field] = value
    row = _one(evidence)
    assert row["Readiness"] == "NOT_READY"
    assert row["Readiness Reason"]


@pytest.mark.parametrize(("confirmed", "not_configured"), [
    (-1, 0), (0, -1), (131, 0), (100, 31), (True, 0), (0, True),
])
def test_invalid_resolved_object_counts_cannot_be_ready(confirmed, not_configured):
    evidence = _evidence()
    evidence["Confirmed Objects"] = confirmed
    evidence["Explicit Not Configured"] = not_configured
    row = _one(evidence)
    assert row["Readiness"] == "NOT_READY"
    assert "counts" in row["Readiness Reason"].lower()


def test_missing_standardization_row_is_not_ready_with_unknown_population():
    row = build_profile_readiness([], (_spec(),))[0]
    assert row["Readiness"] == "NOT_READY"
    assert row["Population Objects"] is None
    assert row["Explicit Not Configured"] in (None, 0)
    assert any(word in row["Readiness Reason"].lower() for word in ("missing", "unavailable"))


def test_some_grid_field_limitations_remain_visible_without_inventing_a_hard_blocker():
    evidence = _evidence(not_configured=0, evidence="PARTIAL")
    evidence["Required Field Status"] = "NOT_EXPOSED_IN_SOME_GRIDS"
    row = _one(evidence)
    assert row["Readiness"] == "READY"
    assert "some grids" in row["Readiness Reason"].lower()


@pytest.mark.parametrize("not_configured", [False, True])
def test_normalized_range_evidence_distinguishes_explicit_absence_from_missing_rows(not_configured):
    result = _collection(ranges=130)
    rows = [_scalar("range", i) for i in range(127)]
    if not_configured:
        rows += [_scalar("range", i, status="NOT_CONFIGURED") for i in range(127, 130)]
    item = _find(_from_normalized(result, rows), "pxe.bootserver.range")
    assert item["Population Objects"] == 130
    assert item["Query Evidence Objects"] == 130
    assert item["Collection Status"] == "COMPLETE"
    assert item["Confirmed Objects"] == 127
    assert item["Explicit Not Configured"] == (3 if not_configured else 0)
    assert item["Resolved Evidence %"] == (100.0 if not_configured else 97.7)
    assert item["Unresolved Objects"] == (0 if not_configured else 3)
    assert item["Readiness"] == "READY"


def test_network_profile_object_level_readiness_uses_only_dhcp_relevant_candidates():
    result = _collection(networks=4)
    result.records["network"][0].update({"members": ["m1"], "network": "10.0.0.0/24", "network_view": "default"})
    result.records["network"][1].update({"network": "10.0.1.0/24", "network_view": "default"})
    result.records["network"][2].update({"network": "10.0.2.0/24", "network_view": "default", "use_options": True})
    result.records["network"][3].update({"network": "10.0.3.0/24", "network_view": "default"})
    result.records["range"] = [{"_ref": "range/LAB/0", "network": "10.0.1.0/24", "network_view": "default"}]
    result.effective_records["network"] = deepcopy(result.records["network"])
    result.coverage.extend([_coverage("range", 1, "raw"), _coverage("range", 1)])

    rows = [_scalar("network", 0), _scalar("network", 1), _scalar("network", 2)]
    standardization = build_standardization([result], result.coverage, rows, [], {})
    item = _find(build_profile_readiness(
        standardization, (_spec("pxe.bootserver.network"),),
        results=[result], scalars=rows, options=[],
    ), "pxe.bootserver.network")

    assert item["Population Basis"] == "DHCP_RELEVANT_NETWORK_CANDIDATES"
    assert item["Source Population Objects"] == 4
    assert item["Population Objects"] == 3
    assert item["Query Evidence Objects"] == 3
    assert item["Confirmed Objects"] == 3
    assert item["Resolved Evidence %"] == 100.0
    assert item["Readiness"] == "READY"


def test_empty_network_candidate_population_is_not_treated_as_no_networks_in_scope():
    result = _collection(networks=2)
    standardization = build_standardization([result], result.coverage, [], [], {})
    item = _find(build_profile_readiness(
        standardization, (_spec("pxe.bootserver.network"),),
        results=[result], scalars=[], options=[],
    ), "pxe.bootserver.network")
    assert item["Source Population Objects"] == 2
    assert item["Population Objects"] == 0
    assert item["Readiness"] == "NOT_READY"
    assert "no dhcp-relevant" in item["Readiness Reason"].lower()


def test_range_authoritative_option_absence_counts_as_explicit_not_configured_for_readiness_only():
    ref = "range/LAB/0"
    result = CollectionResult(
        grid="LAB",
        records={"range": [{
            "_ref": ref, "start_addr": "10.0.0.10", "end_addr": "10.0.0.20",
            "network": "10.0.0.0/24", "network_view": "default",
        }]},
        effective_records={"range": [{
            "_ref": ref, "start_addr": "10.0.0.10", "end_addr": "10.0.0.20",
            "network": "10.0.0.0/24", "network_view": "default",
            "options": [{"inherited": True, "source": "grid:dhcpproperties/LAB", "values": [
                {"num": 51, "name": "dhcp-lease-time", "value": "14400"},
            ]}],
        }]},
        schemas={"range": {"fields": [{"name": "options", "overridden_by": "use_options"}]}},
        coverage=[_coverage("range", 1, "raw"), _coverage("range", 1)],
    )
    options = normalize_options(
        result.grid, "", "2.13.7", result.records, result.effective_records, result.schemas
    )
    standardization = build_standardization([result], result.coverage, [], options, {})
    item = _find(build_profile_readiness(
        standardization, (_spec("dhcp.ntp_servers.range"),),
        results=[result], scalars=[], options=options,
    ), "dhcp.ntp_servers.range")
    assert item["Population Basis"] == "ALL_RANGES"
    assert item["Population Objects"] == 1
    assert item["Confirmed Objects"] == 0
    assert item["Explicit Not Configured"] == 1
    assert item["Resolved Evidence %"] == 100.0
    assert item["Readiness"] == "READY"
    assert not any(row["option_number"] == 42 and row["status"] == "NOT_CONFIGURED" for row in options)


def test_plain_effective_options_do_not_prove_absence_for_readiness():
    ref = "range/LAB/0"
    result = CollectionResult(
        grid="LAB",
        records={"range": [{
            "_ref": ref, "start_addr": "10.0.0.10", "end_addr": "10.0.0.20",
            "network": "10.0.0.0/24", "network_view": "default",
        }]},
        effective_records={"range": [{
            "_ref": ref, "start_addr": "10.0.0.10", "end_addr": "10.0.0.20",
            "network": "10.0.0.0/24", "network_view": "default",
            "options": [{"num": 51, "name": "dhcp-lease-time", "value": "14400"}],
        }]},
        schemas={"range": {"fields": [{"name": "options", "overridden_by": "use_options"}]}},
        coverage=[_coverage("range", 1, "raw"), _coverage("range", 1)],
    )
    options = normalize_options(
        result.grid, "", "2.13.7", result.records, result.effective_records, result.schemas
    )
    standardization = build_standardization([result], result.coverage, [], options, {})
    item = _find(build_profile_readiness(
        standardization, (_spec("dhcp.ntp_servers.range"),),
        results=[result], scalars=[], options=options,
    ), "dhcp.ntp_servers.range")
    assert item["Explicit Not Configured"] == 0
    assert item["Unresolved Objects"] == 1
    assert item["Readiness"] == "NOT_READY"


def test_network_authoritative_option_absence_uses_dhcp_candidate_population():
    ref = "network/LAB/0"
    raw = {
        "_ref": ref, "network": "10.0.0.0/24", "network_view": "default",
        "options": [{"num": 51, "name": "dhcp-lease-time", "value": "3600", "use_option": True}],
    }
    effective = {
        "_ref": ref, "network": "10.0.0.0/24", "network_view": "default",
        "options": [{"inherited": False, "source": "", "values": [
            {"num": 51, "name": "dhcp-lease-time", "value": "3600"},
        ]}],
    }
    result = CollectionResult(
        grid="LAB",
        records={"network": [raw], "range": []},
        effective_records={"network": [effective], "range": []},
        schemas={"network": {"fields": [{"name": "options", "overridden_by": "use_options"}]}},
        coverage=[_coverage("network", 1, "raw"), _coverage("network", 1)],
    )
    options = normalize_options(
        result.grid, "", "2.13.7", result.records, result.effective_records, result.schemas
    )
    standardization = build_standardization([result], result.coverage, [], options, {})
    item = _find(build_profile_readiness(
        standardization, (_spec("dhcp.ntp_servers.network"),),
        results=[result], scalars=[], options=options,
    ), "dhcp.ntp_servers.network")
    assert item["Population Basis"] == "DHCP_RELEVANT_NETWORK_CANDIDATES"
    assert item["Source Population Objects"] == 1
    assert item["Population Objects"] == 1
    assert item["Explicit Not Configured"] == 1
    assert item["Readiness"] == "READY"


def test_no_normalized_parameter_rows_does_not_mean_not_configured():
    item = _find(_from_normalized(_collection(networks=4), []), "pxe.bootserver.network")
    assert item["Population Objects"] == 4
    assert item["Query Evidence Objects"] == 4
    assert item["Collection Status"] == "COMPLETE"
    assert item["Confirmed Objects"] == 0
    assert item["Explicit Not Configured"] == 0
    assert item["Resolved Evidence %"] == 0.0
    assert item["Unresolved Objects"] == 4
    assert item["Readiness"] == "NOT_READY"


def test_all_explicit_not_configured_is_ready_evidence_despite_zero_confirmed_values():
    rows = [_scalar("network", i, status="NOT_CONFIGURED") for i in range(4)]
    item = _find(_from_normalized(_collection(networks=4), rows), "pxe.bootserver.network")
    assert item["Evidence Status"] == "NOT_CONFIGURED"
    assert item["Confirmed Value %"] == 0.0
    assert item["Explicit Not Configured"] == 4
    assert item["Resolved Evidence %"] == 100.0
    assert item["Readiness"] == "READY"


def test_network_and_range_denominators_remain_separate_and_ignore_fixed_addresses():
    result = _collection(networks=2, ranges=1)
    rows = [_scalar("network", 0), _scalar("range", 0)]
    before = _from_normalized(result, rows)
    result.records["fixedaddress"] = [{"_ref": f"fixedaddress/LAB/{i}"} for i in range(50)]
    result.effective_records["fixedaddress"] = deepcopy(result.records["fixedaddress"])
    result.coverage.extend([_coverage("fixedaddress", 50, "raw"), _coverage("fixedaddress", 50)])
    after = _from_normalized(result, rows + [_scalar("fixedaddress", i) for i in range(50)])
    assert after == before
    network = _find(after, "pxe.bootserver.network")
    range_row = _find(after, "pxe.bootserver.range")
    assert (network["Population Objects"], network["Resolved Evidence %"], network["Readiness"]) == (
        2, 50.0, "NOT_READY"
    )
    assert (range_row["Population Objects"], range_row["Resolved Evidence %"], range_row["Readiness"]) == (
        1, 100.0, "READY"
    )


def test_real_collection_failure_is_not_upgraded_by_complete_normalized_rows():
    result = _collection(networks=2)
    next(item for item in result.coverage if item["Object"] == "network"
         and item["Query"] == "effective")["Collection Status"] = "PARTIAL"
    result.errors.append({"grid": "LAB", "object_type": "network", "query": "effective", "error": "ReadTimeout"})
    item = _find(_from_normalized(result, [_scalar("network", i) for i in range(2)]),
                 "pxe.bootserver.network")
    assert item["Resolved Evidence %"] == 100.0
    assert item["Collection Status"] == "PARTIAL"
    assert item["Readiness"] == "NOT_READY"


def test_nonexistent_parameter_id_fails_validation_and_building():
    item = replace(_spec(), source_parameter_id="pxe.invented.network")
    with pytest.raises(ValueError, match="pxe.invented.network"):
        validate_profile_inputs((item,))
    with pytest.raises(ValueError):
        build_profile_readiness([], (item,))


def test_parameter_scope_mismatch_fails_validation():
    with pytest.raises(ValueError, match="[Ss]cope"):
        validate_profile_inputs((replace(_spec(), scope="Range"),))


def test_duplicate_input_key_within_profile_fails_validation():
    first = _spec()
    second = replace(_spec("pxe.bootfile.network"), input_key=first.input_key)
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        validate_profile_inputs((first, second))


def test_same_input_key_is_valid_in_different_profiles():
    validate_profile_inputs((_spec("pxe.bootserver.network"), _spec("pxe.bootserver.range")))


def test_validation_uses_the_supplied_parameter_registry():
    registry = tuple(item for item in PARAMETER_SPECS if item.key != "pxe.bootserver.network")
    with pytest.raises(ValueError, match="pxe.bootserver.network"):
        validate_profile_inputs((_spec(),), parameter_specs=registry)


def test_duplicate_standardization_parameter_rows_fail_instead_of_choosing_one():
    evidence = _evidence()
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        build_profile_readiness([evidence, deepcopy(evidence)])


@pytest.mark.parametrize(("field", "value"), [
    ("Scope", "Range"), ("Object Type", "fixedaddress"), ("Required Field", "options"),
])
def test_mismatched_standardization_evidence_is_rejected(field, value):
    evidence = _evidence()
    evidence[field] = value
    with pytest.raises(ValueError, match="mismatch"):
        build_profile_readiness([evidence])


def test_deterministic_output_copies_metrics_without_mutating_input():
    evidence = [_evidence(), _evidence("pxe.bootserver.range", confirmed=100, not_configured=0)]
    snapshot = deepcopy(evidence)
    first = build_profile_readiness(evidence)
    assert build_profile_readiness(list(reversed(evidence))) == first
    assert evidence == snapshot
    assert len(first) == len(PROFILE_INPUT_SPECS)
    assert all(row["Readiness Reason"] for row in first)
    assert [row["Parameter ID"] for row in first] == [item.source_parameter_id for item in PROFILE_INPUT_SPECS]
    first[0]["Collection Status"] = "CHANGED"
    assert evidence == snapshot


def test_summary_excludes_not_applicable_inputs_from_ready_percentage():
    specs = tuple(item for item in PROFILE_INPUT_SPECS if item.scope == "Network")[:4]
    evidence = []
    for spec, (population, confirmed) in zip(specs, [(100, 100), (100, 90), (100, 79), (0, 0)]):
        evidence.append(_evidence(spec.source_parameter_id, population=population,
                                  confirmed=confirmed, not_configured=0))
    rows = build_profile_readiness(evidence, specs)
    summary = profile_readiness_summary(rows)
    assert len(summary) == 1
    item = summary[0]
    assert item["Profile"] == "Network Profile v1"
    assert item["Candidate Inputs"] == 4
    assert item["Applicable Inputs"] == 3
    assert {key: item[key] for key in ("READY", "CONDITIONAL", "NOT_READY", "NOT_APPLICABLE")} == {
        "READY": 1, "CONDITIONAL": 1, "NOT_READY": 1, "NOT_APPLICABLE": 1
    }
    assert item["Ready Input %"] == 33.3


def test_summary_keeps_profiles_separate_and_all_not_applicable_percentage_undefined():
    specs = (_spec("pxe.bootserver.network"), _spec("pxe.bootserver.range"))
    rows = build_profile_readiness([
        _evidence("pxe.bootserver.network"),
        _evidence("pxe.bootserver.range", population=0, confirmed=0, not_configured=0),
    ], specs)
    summaries = {item["Profile"]: item for item in profile_readiness_summary(rows)}
    network = summaries["Network Profile v1"]
    range_row = summaries["Range Profile v1"]
    assert network["Ready Input %"] == 100.0
    assert network["Candidate Inputs"] == 1
    assert range_row["Applicable Inputs"] == 0
    assert range_row["NOT_APPLICABLE"] == 1
    assert range_row["Ready Input %"] is None
    assert profile_readiness_summary([]) == []


def test_summary_is_deterministic_and_does_not_mutate_readiness_rows():
    rows = build_profile_readiness([_evidence(), _evidence("pxe.bootserver.range")])
    original = deepcopy(rows)
    assert profile_readiness_summary(rows) == profile_readiness_summary(list(reversed(rows)))
    assert rows == original


def test_summary_rejects_duplicate_candidate_rows_instead_of_inflating_counts():
    row = _one(_evidence())
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        profile_readiness_summary([row, deepcopy(row)])


def test_summary_rejects_unknown_readiness_state_instead_of_hiding_it():
    row = _one(_evidence())
    row["Readiness"] = "UNKNOWN_STATE"
    with pytest.raises(ValueError, match="[Uu]nknown"):
        profile_readiness_summary([row])

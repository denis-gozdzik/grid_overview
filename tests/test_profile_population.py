"""DHCP Network profile population must be evidence-backed and deterministic."""
import pytest
from infoblox_inventory.models import CollectionResult
from infoblox_inventory.profile_population import (
    RANGE_SEGMENT_FAILOVER, RANGE_SEGMENT_MEMBER, RANGE_SEGMENT_MS_SERVER,
    RANGE_SEGMENT_NONE, RANGE_SEGMENT_OTHER, RANGE_SEGMENT_UNKNOWN,
    REASON_ACTIVE_OPTION, REASON_MEMBERS, REASON_RANGE_PARENT, REASON_USE_FLAG,
    REASON_INFOBLOX_MEMBER, REASON_INFOBLOX_RANGE_PARENT, REASON_PROFILE_USE_FLAG,
    dhcp_associated_range_keys, dhcp_profile_networks, dhcp_relevant_networks, effective_network_keys,
    infoblox_managed_range_keys, profile_population_rows, profile_population_summary,
    range_association_segment, range_segments,
)


def _result():
    networks = [
        {"_ref": "network/LAB/0", "network": "10.0.0.0/24", "network_view": "default",
         "members": [{"_struct": "dhcpmember", "name": "m1"}]},
        {"_ref": "network/LAB/1", "network": "10.0.1.0/24", "network_view": "default"},
        {"_ref": "network/LAB/2", "network": "10.0.2.0/24", "network_view": "default",
         "use_options": True},
        {"_ref": "network/LAB/3", "network": "10.0.3.0/24", "network_view": "default",
         "options": [{"num": 51, "value": "3600", "use_option": True}]},
        {"_ref": "network/LAB/4", "network": "10.0.4.0/24", "network_view": "default",
         "options": [{"num": 51, "value": "3600", "use_option": False}]},
    ]
    ranges = [
        {"_ref": "range/LAB/0", "network": "10.0.1.0/24", "network_view": "default"},
    ]
    return CollectionResult(
        grid="LAB",
        records={"network": networks, "range": ranges},
        effective_records={"network": networks[:4]},
    )


def test_relevance_reasons_are_union_not_double_counted_population():
    result = _result()
    relevant = dhcp_relevant_networks([result])
    assert len(relevant) == 4
    assert relevant[("LAB", "network/LAB/0")] == {REASON_MEMBERS}
    assert relevant[("LAB", "network/LAB/1")] == {REASON_RANGE_PARENT}
    assert relevant[("LAB", "network/LAB/2")] == {REASON_USE_FLAG}
    assert relevant[("LAB", "network/LAB/3")] == {REASON_ACTIVE_OPTION}
    assert ("LAB", "network/LAB/4") not in relevant


def test_profile_population_summary_exposes_source_and_candidate_denominators():
    rows = profile_population_summary([_result()])
    lab = rows[0]
    total = rows[-1]
    assert lab["Grid"] == "LAB"
    assert lab["All Networks"] == 5
    assert lab["DHCP-Relevant Candidates"] == 4
    assert lab["Candidate %"] == 80.0
    assert lab["With Members"] == 1
    assert lab["Parent of Range"] == 1
    assert lab["Active use_* flag"] == 1
    assert lab["Active DHCP option"] == 1
    assert total["Grid"] == "ALL"
    assert total["All Networks"] == 5
    assert total["DHCP-Relevant Candidates"] == 4


def test_functional_profile_candidates_exclude_topology_only_external_and_container_use_options():
    result = CollectionResult(
        grid="LAB",
        records={
            "network": [
                {"_ref": "network/LAB/member", "network": "10.1.0.0/24", "network_view": "default",
                 "members": [{"_struct": "dhcpmember", "name": "ib-member"}]},
                {"_ref": "network/LAB/ms", "network": "10.2.0.0/24", "network_view": "default",
                 "members": [{"_struct": "msdhcpserver", "ipv4addr": "ms.example"}]},
                {"_ref": "network/LAB/none-parent", "network": "10.3.0.0/24", "network_view": "default"},
                {"_ref": "network/LAB/use-options", "network": "10.4.0.0/24", "network_view": "default",
                 "use_options": True,
                 "options": [{"num": 51, "value": "43200", "use_option": False}]},
                {"_ref": "network/LAB/active-option", "network": "10.5.0.0/24", "network_view": "default",
                 "options": [{"num": 51, "value": "3600", "use_option": True}]},
                {"_ref": "network/LAB/ddns", "network": "10.6.0.0/24", "network_view": "default",
                 "use_enable_ddns": True},
                {"_ref": "network/LAB/member-parent", "network": "10.7.0.0/24", "network_view": "default"},
            ],
            "range": [
                {"_ref": "range/LAB/ms", "network": "10.2.0.0/24", "network_view": "default",
                 "server_association_type": "MS_SERVER"},
                {"_ref": "range/LAB/none", "network": "10.3.0.0/24", "network_view": "default",
                 "server_association_type": "NONE"},
                {"_ref": "range/LAB/member", "network": "10.7.0.0/24", "network_view": "default",
                 "server_association_type": "MEMBER"},
            ],
        },
    )

    candidates = dhcp_profile_networks([result])
    assert set(candidates) == {
        ("LAB", "network/LAB/member"),
        ("LAB", "network/LAB/active-option"),
        ("LAB", "network/LAB/ddns"),
        ("LAB", "network/LAB/member-parent"),
    }
    assert candidates[("LAB", "network/LAB/member")] == {REASON_INFOBLOX_MEMBER}
    assert candidates[("LAB", "network/LAB/active-option")] == {REASON_ACTIVE_OPTION}
    assert candidates[("LAB", "network/LAB/ddns")] == {REASON_PROFILE_USE_FLAG}
    assert candidates[("LAB", "network/LAB/member-parent")] == {REASON_INFOBLOX_RANGE_PARENT}
    assert ("LAB", "network/LAB/ms") not in candidates
    assert ("LAB", "network/LAB/none-parent") not in candidates
    assert ("LAB", "network/LAB/use-options") not in candidates


def test_effective_network_keys_do_not_claim_missing_page_objects():
    keys = effective_network_keys([_result()])
    assert len(keys) == 4
    assert ("LAB", "network/LAB/4") not in keys



@pytest.mark.parametrize(("value", "expected"), [
    ("MS_SERVER", RANGE_SEGMENT_MS_SERVER),
    ("ms-server", RANGE_SEGMENT_MS_SERVER),
    ("MEMBER", RANGE_SEGMENT_MEMBER),
    ("FAILOVER", RANGE_SEGMENT_FAILOVER),
    ("FAILOVER_ASSOCIATION", RANGE_SEGMENT_FAILOVER),
    ("NONE", RANGE_SEGMENT_NONE),
    ("", RANGE_SEGMENT_NONE),
    (None, RANGE_SEGMENT_NONE),
    ("future-value", RANGE_SEGMENT_OTHER),
])
def test_range_association_classification_is_explicit_and_conservative(value, expected):
    segment, raw = range_association_segment({"server_association_type": value})
    assert segment == expected
    if expected == RANGE_SEGMENT_OTHER:
        assert raw == "future-value"


def test_missing_range_association_field_is_unknown_not_none():
    segment, raw = range_association_segment({})
    assert segment == RANGE_SEGMENT_UNKNOWN
    assert raw == ""


def test_non_scalar_range_association_is_unknown_not_coerced():
    segment, raw = range_association_segment({"server_association_type": {"future": True}})
    assert segment == RANGE_SEGMENT_UNKNOWN
    assert "future" in raw


def test_range_population_segments_match_association_semantics():
    values = ["MS_SERVER"] * 4 + ["MEMBER"] * 2 + ["FAILOVER"] + ["NONE"]
    result = CollectionResult(
        grid="LAB",
        records={"range": [
            {"_ref": f"range/LAB/{i}", "server_association_type": value}
            for i, value in enumerate(values)
        ]},
    )
    segments = range_segments([result])
    assert len(segments[RANGE_SEGMENT_MS_SERVER]) == 4
    assert len(segments[RANGE_SEGMENT_MEMBER]) == 2
    assert len(segments[RANGE_SEGMENT_FAILOVER]) == 1
    assert len(segments[RANGE_SEGMENT_NONE]) == 1
    assert len(dhcp_associated_range_keys([result])) == 7
    assert len(infoblox_managed_range_keys([result])) == 3


def test_profile_population_rows_expose_network_and_range_denominators_without_quality_labels():
    result = _result()
    result.records["range"] = [
        {"_ref": "range/LAB/0", "server_association_type": "MS_SERVER"},
        {"_ref": "range/LAB/1", "server_association_type": "MEMBER"},
        {"_ref": "range/LAB/2", "server_association_type": "NONE"},
        {"_ref": "range/LAB/3", "server_association_type": "future-value"},
    ]
    rows = profile_population_rows([result])
    by_basis = {(row["Population Basis"], row["Segment"]): row for row in rows}
    assert by_basis[("ALL_NETWORKS", "ALL")]["Object Count"] == 5
    assert by_basis[("DHCP_RELEVANT_NETWORK_CANDIDATES", "RELEVANT")]["Object Count"] == 3
    assert by_basis[("DHCP_PROFILE_NETWORK_CANDIDATES", "CANDIDATE")]["Object Count"] == 2
    assert by_basis[("ALL_RANGES", "ALL")]["Object Count"] == 4
    assert by_basis[("DHCP_ASSOCIATED_RANGES", "ASSOCIATED")]["Object Count"] == 2
    assert by_basis[("INFOBLOX_MANAGED_RANGES", "INFOBLOX_MANAGED")]["Object Count"] == 1
    assert by_basis[("RANGE_SEGMENT_MS_SERVER", "MS_SERVER")]["Object Count"] == 1
    assert by_basis[("RANGE_SEGMENT_NONE", "NONE")]["Object Count"] == 1
    other = by_basis[("RANGE_SEGMENT_OTHER", "OTHER")]
    assert other["Object Count"] == 1
    assert other["Observed Association Values"] == "future-value"
    assert all("compliant" not in str(row).lower() for row in rows)

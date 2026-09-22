"""DHCP Network profile population must be evidence-backed and deterministic."""
from infoblox_inventory.models import CollectionResult
from infoblox_inventory.profile_population import (
    REASON_ACTIVE_OPTION, REASON_MEMBERS, REASON_RANGE_PARENT, REASON_USE_FLAG,
    dhcp_relevant_networks, effective_network_keys, profile_population_summary,
)


def _result():
    networks = [
        {"_ref": "network/LAB/0", "network": "10.0.0.0/24", "network_view": "default",
         "members": ["m1"]},
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


def test_effective_network_keys_do_not_claim_missing_page_objects():
    keys = effective_network_keys([_result()])
    assert len(keys) == 4
    assert ("LAB", "network/LAB/4") not in keys

"""Authoritative effective option groups can prove assessed option absence."""
from infoblox_inventory.normalize import normalize_options


def _schema():
    return {"network": {"fields": [{"name": "options", "overridden_by": "use_options"}]},
            "range": {"fields": [{"name": "options", "overridden_by": "use_options"}]}}


def test_absent_assessed_option_in_authoritative_range_groups_is_not_configured():
    records = {
        "range": [{
            "_ref": "range/LAB/1", "start_addr": "10.0.0.10", "end_addr": "10.0.0.20",
            "network": "10.0.0.0/24", "network_view": "default",
            "options": [{"num": 42, "name": "ntp-servers", "value": "192.0.2.42", "use_option": False}],
            "use_options": False,
        }]
    }
    effective = {
        "range": [{
            "_ref": "range/LAB/1", "start_addr": "10.0.0.10", "end_addr": "10.0.0.20",
            "network": "10.0.0.0/24", "network_view": "default",
            "options": [{
                "inherited": True, "source": "grid:dhcpproperties/example:LAB",
                "values": [{"num": 51, "name": "dhcp-lease-time", "value": "14400"}],
            }],
        }]
    }
    rows = normalize_options("LAB", "https://grid", "2.13.7", records, effective, _schema())
    ntp = next(row for row in rows if row["object_type"] == "range" and row["option_number"] == 42)
    assert ntp["status"] == "NOT_CONFIGURED"
    assert ntp["effective_value"] is None
    assert ntp["source_level"] == "NOT_DEFINED"
    assert ntp["raw_value"] == "192.0.2.42"
    assert ntp["inheritance_details"]["absence_in_authoritative_options"] is True


def test_authoritative_groups_emit_not_configured_for_each_bounded_assessed_option_only():
    records = {"network": [{"_ref": "network/LAB/1", "network": "10.0.0.0/24", "network_view": "default"}]}
    effective = {"network": [{
        "_ref": "network/LAB/1", "network": "10.0.0.0/24", "network_view": "default",
        "options": [{"inherited": False, "source": "", "values": [
            {"num": 6, "name": "domain-name-servers", "value": "192.0.2.53"},
        ]}],
    }]}
    rows = normalize_options("LAB", "https://grid", "2.13.7", records, effective, _schema())
    by_number = {row["option_number"]: row for row in rows if row["option_number"] is not None}
    assert by_number[6]["status"] == "COMPLETE"
    assert {3, 15, 42, 51, 66, 67, 119} <= set(by_number)
    assert all(by_number[number]["status"] == "NOT_CONFIGURED"
               for number in (3, 15, 42, 51, 66, 67, 119))


def test_plain_or_malformed_effective_options_never_infer_absence():
    records = {"range": [{
        "_ref": "range/LAB/1", "start_addr": "10.0.0.10", "end_addr": "10.0.0.20",
        "network": "10.0.0.0/24", "network_view": "default",
    }]}
    plain_effective = {"range": [{
        "_ref": "range/LAB/1", "start_addr": "10.0.0.10", "end_addr": "10.0.0.20",
        "network": "10.0.0.0/24", "network_view": "default",
        "options": [{"num": 51, "name": "dhcp-lease-time", "value": "14400"}],
    }]}
    rows = normalize_options("LAB", "https://grid", "2.13.7", records, plain_effective, _schema())
    assert not any(row["option_number"] == 42 and row["status"] == "NOT_CONFIGURED" for row in rows)

    malformed_effective = {"range": [{
        "_ref": "range/LAB/1", "start_addr": "10.0.0.10", "end_addr": "10.0.0.20",
        "network": "10.0.0.0/24", "network_view": "default",
        "options": [{"inherited": True, "source": "grid:dhcpproperties/example:LAB", "values": "bad"}],
    }]}
    rows = normalize_options("LAB", "https://grid", "2.13.7", records, malformed_effective, _schema())
    assert not any(row["option_number"] == 42 and row["status"] == "NOT_CONFIGURED" for row in rows)


def test_empty_effective_option_list_is_not_used_as_authoritative_absence():
    records = {"network": [{"_ref": "network/LAB/1", "network": "10.0.0.0/24", "network_view": "default"}]}
    effective = {"network": [{
        "_ref": "network/LAB/1", "network": "10.0.0.0/24", "network_view": "default",
        "options": [],
    }]}
    rows = normalize_options("LAB", "https://grid", "2.13.7", records, effective, _schema())
    assert not any(row["status"] == "NOT_CONFIGURED" for row in rows)

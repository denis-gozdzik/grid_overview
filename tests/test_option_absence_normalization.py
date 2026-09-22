"""Normalization must stay evidence-preserving; profile absence inference is separate."""
from infoblox_inventory.normalize import normalize_options


def _schema():
    return {"network": {"fields": [{"name": "options", "overridden_by": "use_options"}]},
            "range": {"fields": [{"name": "options", "overridden_by": "use_options"}]}}


def test_authoritative_absence_does_not_create_synthetic_normalized_option_rows():
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
    assert ntp["status"] == "PARTIAL"
    assert ntp["effective_value"] is None
    assert not any(row["status"] == "NOT_CONFIGURED" and row["option_number"] == 42 for row in rows)


def test_vendor_option_groups_are_not_polluted_by_synthetic_dhcp_absence_rows():
    ref = "network/example:10.77.10.0/24/default"
    effective = {"network": [{"_ref": ref, "options": [{"inherited": False, "source": "", "values": [
        {"name": "custom", "num": 200, "vendor_class": "A", "value": "one", "use_option": False},
        {"name": "custom", "num": 200, "vendor_class": "B", "value": "two", "use_option": False},
    ]}]}]}
    rows = normalize_options("G", "", "2.13.7", {}, effective)
    assert {(row["vendor_class"], row["effective_value"]) for row in rows} == {("A", "one"), ("B", "two")}

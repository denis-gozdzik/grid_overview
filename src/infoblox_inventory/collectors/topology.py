"""Assessment fields verified against LAB WAPI 2.13.7 schemas on 2026-09-20.

Use flags are added by the existing collector from schema overridden_by metadata.
These are stored configuration objects, not resolved inheritance results.
"""

TEMPLATE_FIELDS = [
    "name", "comment", "options", "bootfile", "bootserver", "nextserver", "deny_bootp",
    "enable_pxe_lease_time", "pxe_lease_time", "ignore_dhcp_option_list_request",
]

TOPOLOGY_OBJECTS: dict[str, tuple[str, str, list[str]]] = {
    "dhcpfailover": (
        "DHCP failover associations and/or Grid Members", "DHCP Failover", [
            "name", "comment", "association_type", "primary", "secondary",
            "primary_server_type", "secondary_server_type", "primary_state", "secondary_state",
            "failover_port", "load_balance_split", "max_client_lead_time", "max_load_balance_delay",
            "max_response_delay", "max_unacked_updates", "recycle_leases", "ms_association_mode",
            "ms_failover_mode", "ms_failover_partner", "ms_server", "ms_hotstandby_partner_role",
            "ms_state", "ms_previous_state", "ms_is_conflict", "ms_enable_authentication",
            "ms_enable_switchover_interval", "ms_switchover_interval",
        ],
    ),
    "networktemplate": (
        "Existing network templates", "Network Templates", [
            *TEMPLATE_FIELDS, "netmask", "allow_any_netmask", "members", "delegated_member",
            "range_templates", "fixed_address_templates", "authority", "lease_scavenge_time", "recycle_leases",
        ],
    ),
    "rangetemplate": (
        "Existing range templates", "Range Templates", [
            *TEMPLATE_FIELDS, "offset", "number_of_addresses", "server_association_type", "member",
            "ms_server", "delegated_member", "failover_association", "exclude", "lease_scavenge_time", "recycle_leases",
        ],
    ),
    "fixedaddresstemplate": (
        "Existing fixed address templates", "Fixed Address Templates", [
            *TEMPLATE_FIELDS, "offset", "number_of_addresses",
        ],
    ),
    "dhcpoptionspace": (
        "DHCP option spaces", "Option Spaces", ["name", "comment", "space_type", "option_definitions"],
    ),
    "dhcpoptiondefinition": (
        "DHCP option definitions", "Option Definitions", ["name", "code", "space", "type"],
    ),
}

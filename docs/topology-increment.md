# Reusable DHCP topology increment

Runtime evidence: authorized LAB discovery on 2026-09-20, WAPI **2.13.7**. The validated core client, RAW/effective normalization, inheritance, version-1 archive and offline workflow are unchanged. The report extension uses the existing workbook writer.

## Existing support and bounded change

Before this increment, failover, network/range templates and option definitions had shallow generic collection and JSON-oriented inventory rows. Fixed-address templates and option spaces were not registered. There were no typed topology records. The new `topology` selector includes exactly the six objects below. Fixed-address objects, filters, DNS, DDNS and Extensible Attributes are outside this increment.

## Live GETs executed

Base: `https://192.168.88.243/wapi/v2.13.7`. All 13 HTTP responses were 200. No appliance modification or inheritance query was performed.

```text
GET /?_schema=1
GET /dhcpfailover?_schema=1&_schema_version=2&_schema_searchable=1
GET /networktemplate?_schema=1&_schema_version=2&_schema_searchable=1
GET /rangetemplate?_schema=1&_schema_version=2&_schema_searchable=1
GET /fixedaddresstemplate?_schema=1&_schema_version=2&_schema_searchable=1
GET /dhcpoptionspace?_schema=1&_schema_version=2&_schema_searchable=1
GET /dhcpoptiondefinition?_schema=1&_schema_version=2&_schema_searchable=1
```

Each object then received one paginated data GET with `_paging=1`, `_return_as_object=1`, `_max_results=1000` and `_return_fields` equal to its exact list below. All six result envelopes fit on one page; multi-page behavior is exercised by synthetic HTTP tests. `_ref` is returned intrinsically by WAPI.

The local coordination helper stopped after schema discovery because its signal file contained a UTF-8 BOM. Collection resumed with a new hidden password prompt and the saved schema cache; no schema GETs were repeated. The retained log records both the local error and successful data collection.

## Exact readable field selection

Lists include `use_*` flags discovered from the live schema `overridden_by` metadata. They are not guessed flag names.

### `dhcpfailover`

Schema: 34 fields; selected: 30 readable fields.

```text
name, comment, association_type, primary, secondary, primary_server_type, secondary_server_type, primary_state, secondary_state, failover_port, load_balance_split, max_client_lead_time, max_load_balance_delay, max_response_delay, max_unacked_updates, recycle_leases, ms_association_mode, ms_failover_mode, ms_failover_partner, ms_server, ms_hotstandby_partner_role, ms_state, ms_previous_state, ms_is_conflict, ms_enable_authentication, ms_enable_switchover_interval, ms_switchover_interval, use_failover_port, use_recycle_leases, use_ms_switchover_interval
```

### `networktemplate`

Schema: 70 fields; selected: 29 readable fields.

```text
name, comment, options, bootfile, bootserver, nextserver, deny_bootp, enable_pxe_lease_time, pxe_lease_time, ignore_dhcp_option_list_request, netmask, allow_any_netmask, members, delegated_member, range_templates, fixed_address_templates, authority, lease_scavenge_time, recycle_leases, use_options, use_bootfile, use_bootserver, use_nextserver, use_deny_bootp, use_pxe_lease_time, use_ignore_dhcp_option_list_request, use_authority, use_lease_scavenge_time, use_recycle_leases
```

### `rangetemplate`

Schema: 63 fields; selected: 29 readable fields.

```text
name, comment, options, bootfile, bootserver, nextserver, deny_bootp, enable_pxe_lease_time, pxe_lease_time, ignore_dhcp_option_list_request, offset, number_of_addresses, server_association_type, member, ms_server, delegated_member, failover_association, exclude, lease_scavenge_time, recycle_leases, use_options, use_bootfile, use_bootserver, use_nextserver, use_deny_bootp, use_pxe_lease_time, use_ignore_dhcp_option_list_request, use_lease_scavenge_time, use_recycle_leases
```

### `fixedaddresstemplate`

Schema: 27 fields; selected: 19 readable fields.

```text
name, comment, options, bootfile, bootserver, nextserver, deny_bootp, enable_pxe_lease_time, pxe_lease_time, ignore_dhcp_option_list_request, offset, number_of_addresses, use_options, use_bootfile, use_bootserver, use_nextserver, use_deny_bootp, use_pxe_lease_time, use_ignore_dhcp_option_list_request
```

### `dhcpoptionspace`

Schema: 4 fields; selected: 4 readable fields.

```text
name, comment, space_type, option_definitions
```

### `dhcpoptiondefinition`

Schema: 4 fields; selected: 4 readable fields.

```text
name, code, space, type
```

## Schema findings

- `dhcpoptiondefinition` exposes only `name`, `code`, `space`, `type`; the old requested `comment` field is absent and has been removed.
- Template options contain `name`, `num`, `vendor_class`, `value`, `use_option`. Options are stored values, never asserted effective values.
- Network-template `members` contains DHCP-member/MS-server structures. Available member fields are `name`, `ipv4addr`, `ipv6addr`; a member type is not inferred from an address alone.
- Range-template `ms_server` is an address structure; failover `ms_server`, `primary`, `secondary` and `ms_failover_partner` are strings.
- Range exclusions expose `offset`, `number_of_addresses`, `comment`. Template links and option-definition links are preserved as supplied string arrays.
- The live `DHCP` option space uses definition names in `option_definitions`, not object refs. Its `space_type` is `PREDEFINED_DHCP`; the schema also allows `VENDOR_SPACE`.
- Write-only `ms_shared_secret`, failover action fields and out-of-scope configuration fields are excluded.

## Records, coverage and Excel

Six explicit dataclasses represent failover, network/range/fixed-address templates, option spaces and definitions. Nested options, member/server associations and range exclusions have typed records. Missing optional values remain `None`; invalid types produce `PARTIAL` plus field paths without coercion. Each record retains an independent full `raw` copy and unknown `extra_fields`, including nested data.

Collection coverage retains `EMPTY`, `COMPLETE`, `PARTIAL`, `ERROR` and `NOT_EXPOSED_BY_WAPI`. Supplemental normalization rows assess parsed records only and do not override a partial query. No synthetic inventory rows are emitted for empty collections.

Workbook sheets: `DHCP_Failover`, `Network_Templates`, `Range_Templates`, `Fixed_Address_Templates`, `Option_Spaces`, `Option_Definitions`, plus `Template_Options`. They expose typed columns, observed use flags, refs, unknown fields and normalization issues. Empty collected objects retain useful column headers. Template options expose `stored_value`, `use_option`, `use_options` and `RAW_CONFIGURATION`, without an effective-value claim. Existing report sheets and safe literal Excel text handling remain in place.

## Live counts and limitations

| Object | Rows | Collection status |
| --- | ---: | --- |
| `dhcpfailover` | 0 | EMPTY |
| `networktemplate` | 0 | EMPTY |
| `rangetemplate` | 0 | EMPTY |
| `fixedaddresstemplate` | 0 | EMPTY |
| `dhcpoptionspace` | 1 | COMPLETE |
| `dhcpoptiondefinition` | 95 | COMPLETE |

All 96 returned records normalized successfully. LAB contains no failover associations or templates, so populated behavior for those four types is schema-backed and synthetic, not live-validated. The option-space comment was absent from this response and remains unknown. No appliance objects were created to fill these gaps.

The accepted Member inheritance limitation is unchanged: its plain-shaped `_inheritance=True` response remains unresolved/PARTIAL. NIOS 9.1 LAB results do not establish production NIOS 9.0.7 behavior or service-account permissions. GET snapshots are not atomic.

Actual schemas and six response pages are included under `tests/fixtures/topology_lab_20260920` with SHA-256 provenance. Synthetic populated examples are explicitly labeled in tests. `.gitattributes` preserves the captured JSON bytes across Git checkouts. Local raw archives, reports, logs, environment files and private config are ignored by `.gitignore`; only `config/grids.example.yaml` is allowed. Changes remain in the working tree; no commit or history rewrite was performed.

## Files changed in this increment

- Existing: `src/infoblox_inventory/collectors/core.py` (registry and aliases only), `src/infoblox_inventory/report.py` (additive typed sheets and coverage), `README.md`.
- New: `src/infoblox_inventory/collectors/topology.py` (verified fields), `src/infoblox_inventory/topology.py` (typed records), `.gitignore`, `.gitattributes`, this document.
- Tests: `tests/test_topology_collection.py`, `tests/test_topology_normalization.py`, `tests/test_topology_report.py`.
- Fixtures: six schemas, six response pages and `provenance.json` under `tests/fixtures/topology_lab_20260920`.
- Ignored local evidence: `output/topology-20260920T062102Z`, containing schema discovery, exact field selection, GET log, immutable RAW archive, reports and validation results.

## Verification results

- Full suite: **205 passed** (`python -m pytest -q -p no:cacheprovider`). Added 52 tests for six-object pagination/scope, schema variation, errors and partial pages, typed nested structures, unknown data, live captures, coverage and Excel output.
- Two offline topology builds with Requests and socket connections blocked: identical workbook cell matrices and Markdown files; all 14 topology RAW/archive files unchanged.
- Rebuilt the previously validated core snapshot: workbook cells and Markdown identical to its original report; all 17 baseline RAW/archive files unchanged.
- SHA-256 checks confirm `client.py`, `schema.py`, `storage.py`, `normalize.py`, `cli.py`, `config.py`, `analysis.py`, and `models.py` unchanged.

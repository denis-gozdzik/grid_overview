# DHCP reservations and filters increment

Validated on 2026-09-20 against LAB-GRID at `https://192.168.88.243`, using WAPI **2.13.7** and GET-only requests. The corrected collection has no errors and no populated objects. **301 tests passed**. Core and topology baseline reports remain identical, and offline reconstruction remains reproducible.

## Baseline and scope

Before this increment, the validated baseline contained the core DHCP and six topology/template collectors, immutable version-1 RAW storage, offline replay, schema-derived override flags, and separate RAW/effective normalization. It also had shallow `fixedaddress`, `filtermac`, and `filteroption` registry entries and generic report rows, without reservation/filter typed records. The old `filtermac.pattern` and `filteroption.match` selections were not exposed by the captured runtime schemas; this increment uses the actual readable matching fields.

The new `reservations_filters` alias selects the twelve objects below. `reservations` selects the six reservation/context types; `filters` selects the six filter/MAC-entry types; `fixed_addresses` still selects only `fixedaddress`. Selecting `superhostchild` also selects its `superhost` dependency. No appliance writes were performed.

Host records are DHCP context, not automatically reservations. Only the selected host fields and IPv4 DHCP child configuration are assessed. DDNS settings and `extattrs` are retained only as reservation metadata; no DNS inventory, DDNS implementation, EA inventory/interpretation, general DNS records, or filter EA collection is added. Discovery credentials and guest contact data are excluded.

## Discovered objects and selected readable fields

All twelve objects are advertised by the LAB root schema. The root exposes no separate object named `reservation`. The table counts top-level schema entries, including search-only entries; it is not a count of readable fields. Selected field counts include the runtime `overridden_by` flags listed below. `_ref` is retained from returned objects and mapped to `object_ref`; it is not a guessed `_return_fields` field.

| WAPI object | Schema entries | Selected readable fields | Corrected RAW count/status | Excel sheet |
| --- | ---: | ---: | --- | --- |
| `fixedaddress` | 155 | 41 | 0 / EMPTY (successful GET) | `Fixed_Reservations` |
| `record:host` | 41 | 6 | 0 / EMPTY (successful GET) | `Host_DHCP_Context` |
| `record:host_ipv4addr` | 126 | 26 | 0 / EMPTY (successful GET) | `Host_IPv4_DHCP` |
| `roaminghost` | 53 | 40 | 0 / EMPTY (successful GET) | `Roaming_Hosts` |
| `superhost` | 7 | 4 | 0 / EMPTY (successful GET) | `Superhost_DHCP` |
| `superhostchild` | 11 | 9 | 0 / EMPTY (empty parent dependency; no child GET) | `Superhost_Fixed_Links` |
| `filtermac` | 10 | 8 | 0 / EMPTY (successful GET) | `MAC_Filters` |
| `macfilteraddress` | 20 | 8 | 0 / EMPTY (successful GET) | `MAC_Filter_Addresses` |
| `filteroption` | 12 | 11 | 0 / EMPTY (successful GET) | `Option_Filters` |
| `filterrelayagent` | 13 | 12 | 0 / EMPTY (successful GET) | `Relay_Agent_Filters` |
| `filterfingerprint` | 4 | 3 | 0 / EMPTY (successful GET) | `Fingerprint_Filters` |
| `filternac` | 6 | 5 | 0 / EMPTY (successful GET) | `NAC_Filters` |

All successful initial and corrected data responses were single-page empty envelopes. Fixed-address effective collection also returned **0 / EMPTY**. There are no non-empty live objects or live normalized records in this increment.

### `fixedaddress`

**Fields:** `ipv4addr`, `mac`, `dhcp_client_identifier`, `client_identifier_prepend_zero`, `name`, `network`, `network_view`, `match_client`, `agent_circuit_id`, `agent_remote_id`, `enable_ddns`, `ddns_hostname`, `ddns_domainname`, `options`, `ms_options`, `ms_server`, `cloud_info`, `comment`, `extattrs`, `disable`, `is_invalid_mac`, `reserved_interface`, `logic_filter_rules`, `ignore_dhcp_option_list_request`, `bootfile`, `bootserver`, `nextserver`, `deny_bootp`, `enable_pxe_lease_time`, `pxe_lease_time`.

**Additional schema-derived flags:** `use_enable_ddns`, `use_ddns_domainname`, `use_options`, `use_ms_options`, `use_logic_filter_rules`, `use_ignore_dhcp_option_list_request`, `use_bootfile`, `use_bootserver`, `use_nextserver`, `use_deny_bootp`, `use_pxe_lease_time`.

### `record:host`

**Fields:** `name`, `network_view`, `disable`, `comment`, `extattrs`, `ipv4addrs`.

**Additional schema-derived flags:** None.

### `record:host_ipv4addr`

**Fields:** `ipv4addr`, `mac`, `host`, `network`, `network_view`, `configure_for_dhcp`, `match_client`, `options`, `logic_filter_rules`, `is_invalid_mac`, `reserved_interface`, `ignore_client_requested_options`, `bootfile`, `bootserver`, `nextserver`, `deny_bootp`, `enable_pxe_lease_time`, `pxe_lease_time`.

**Additional schema-derived flags:** `use_options`, `use_logic_filter_rules`, `use_ignore_client_requested_options`, `use_bootfile`, `use_bootserver`, `use_nextserver`, `use_deny_bootp`, `use_pxe_lease_time`.

### `roaminghost`

**Fields:** `name`, `address_type`, `mac`, `dhcp_client_identifier`, `client_identifier_prepend_zero`, `match_client`, `network_view`, `enable_ddns`, `ddns_hostname`, `ddns_domainname`, `force_roaming_hostname`, `options`, `comment`, `extattrs`, `disable`, `ignore_dhcp_option_list_request`, `ipv6_duid`, `ipv6_mac_address`, `ipv6_match_option`, `ipv6_options`, `preferred_lifetime`, `valid_lifetime`, `bootfile`, `bootserver`, `nextserver`, `deny_bootp`, `enable_pxe_lease_time`, `pxe_lease_time`.

**Additional schema-derived flags:** `use_enable_ddns`, `use_ddns_domainname`, `use_options`, `use_ignore_dhcp_option_list_request`, `use_ipv6_options`, `use_preferred_lifetime`, `use_valid_lifetime`, `use_bootfile`, `use_bootserver`, `use_nextserver`, `use_deny_bootp`, `use_pxe_lease_time`.

### `superhost`

**Fields:** `name`, `comment`, `disabled`, `dhcp_associated_objects`.

**Additional schema-derived flags:** None.

### `superhostchild`

**Fields:** `name`, `comment`, `data`, `disabled`, `network_view`, `parent`, `record_parent`, `type`, `associated_object`.

**Additional schema-derived flags:** None.

### `filtermac`

**Fields:** `name`, `comment`, `disable`, `default_mac_address_expiration`, `enforce_expiration_times`, `never_expires`, `lease_time`, `options`.

**Additional schema-derived flags:** None.

### `macfilteraddress`

**Fields:** `mac`, `filter`, `comment`, `authentication_time`, `expiration_time`, `never_expires`, `fingerprint`, `is_registered_user`.

**Additional schema-derived flags:** None.

### `filteroption`

**Fields:** `name`, `comment`, `expression`, `apply_as_class`, `option_space`, `option_list`, `lease_time`, `bootfile`, `bootserver`, `next_server`, `pxe_lease_time`.

**Additional schema-derived flags:** None.

### `filterrelayagent`

**Fields:** `name`, `comment`, `is_circuit_id`, `circuit_id_name`, `is_circuit_id_substring`, `circuit_id_substring_offset`, `circuit_id_substring_length`, `is_remote_id`, `remote_id_name`, `is_remote_id_substring`, `remote_id_substring_offset`, `remote_id_substring_length`.

**Additional schema-derived flags:** None.

### `filterfingerprint`

**Fields:** `name`, `comment`, `fingerprint`.

**Additional schema-derived flags:** None.

### `filternac`

**Fields:** `name`, `comment`, `expression`, `lease_time`, `options`.

**Additional schema-derived flags:** None.

## Request forms and the real parent constraint

```text
GET https://192.168.88.243/wapi/v2.13.7/?_schema=1
GET https://192.168.88.243/wapi/v2.13.7/<object>?_schema=1&_schema_version=2&_schema_searchable=1
GET https://192.168.88.243/wapi/v2.13.7/<object>?_max_results=1000&_return_fields=<exact selected fields>&_paging=1&_return_as_object=1
```

For `fixedaddress`, the unchanged effective query additionally supplies `_inheritance=True`. No other new object receives an inheritance request. For subsequent pages the existing client sends only `_page_id=<opaque next_page_id>`; continuation tokens carry the original query. No continuation GET was needed in this empty LAB.

The initial `superhostchild` query used the schema-supported `type=FixedAddress` filter. Both that request and a GET-only diagnostic returned HTTP 400. The retained real response states: `Search fields must contain 'parent'`. The runtime schema marks `parent` as searchable with exact equality but does not express this mandatory dependency. The [captured diagnostic](../tests/fixtures/reservations_lab_20260920/diagnostics/superhostchild-parent-required.json) is the reason for the correction.

The corrected collector first obtains complete Superhost names and then plans this request for each observed name:

```text
GET https://192.168.88.243/wapi/v2.13.7/superhostchild?_max_results=1000&_return_fields=name,comment,data,disabled,network_view,parent,record_parent,type,associated_object&type=FixedAddress&parent=<URL-encoded observed superhost name>&_paging=1&_return_as_object=1
```

No parent name is invented or transformed. Since the corrected LAB Superhost inventory is completely empty, **zero child requests** were executed. Child coverage is `EMPTY` with an explicit dependency note. No child response file was fabricated. With populated parents, one version-1 child query groups optional `subqueries` metadata containing each exact initial parameter set, status, count and page ownership; original response pages receive consecutive numbers across parents. Missing/incomplete parent discovery prevents an `EMPTY` claim, and failed child reads retain available pages with partial/error coverage.

| Phase | GETs | HTTP 200 | HTTP 400 |
| --- | ---: | ---: | ---: |
| Root plus twelve schemas | 13 | 13 | 0 |
| Initial twelve RAW queries plus fixed-address effective | 13 | 12 | 1 |
| Diagnostic reproduction of rejected child query | 1 | 0 | 1 |
| Corrected eleven RAW queries plus fixed-address effective | 12 | 12 | 0 |
| Total | **39** | **37** | **2** |

The corrected run reused the actual schemas already captured by this run, so no additional schema requests were necessary. The two failed requests remain part of the audit record; they are not counted as successful empty results.

## Typed records, nested evidence and coverage

`reservations.py` adds twelve typed record classes corresponding to the twelve WAPI types. Nested types preserve DHCP options, Microsoft DHCP options, logic-filter rules, cloud information/delegated members, host IPv4 children, and Superhost association references or embedded objects. Existing topology option/member structures are reused without modification. EA dictionaries remain opaque JSON metadata.

Each parsed record and nested object retains a separate deep copy of full raw JSON and `extra_fields`. Invalid types are recorded as issues without boolean/integer coercion. Unknown fields and malformed elements remain in raw evidence. Option and relationship rows preserve original array indexes even when invalid elements are omitted from typed lists. Reference strings are not resolved, and filter names such as `Corporate` or `Allowed` do not imply behavior.

| Status | Meaning in this increment |
| --- | --- |
| `COMPLETE` | A supported query completed with records, or the available record fields were parsed without type issues. Normalization completeness does not establish query completeness or operational policy. |
| `PARTIAL` | Requested readable coverage is incomplete, parsing found invalid types, host DHCP evidence is unresolved, parent discovery is incomplete, or a failed read retained usable records. |
| `EMPTY` | A successful completed query returned zero records; for child objects, complete empty parent discovery establishes zero applicable child requests and is explicitly documented. |
| `NOT_CONFIGURED` | Explicit IPv4 host child flags show DHCP is not configured, or a known host IPv4 child list is empty. This is not inferred from names or absent fields. |
| `NOT_EXPOSED_BY_WAPI` | The runtime root/schema omits an object/field or the field is not readable. Includes write-only template origin fields. |
| `MANUAL_REVIEW_REQUIRED` | Populated filter evidence requires review of policy/consumer meaning; existing organizational review items remain. |
| `ERROR` | A schema or data request failed without usable records. Errors are never converted into evidence of absence. |

IPv4 host `configure_for_dhcp=True`, `False`, and missing/invalid values map to `COMPLETE`, `NOT_CONFIGURED`, and `PARTIAL` configuration observations respectively. Unresolved child references remain `PARTIAL`. These flags do not establish service activation, address availability, DHCPv6 configuration, or a successful lease. Empty live inventories retain collection `EMPTY` coverage and do not receive invented normalization rows.

## Excel representation

The twelve object sheets in the table above retain headers even when empty. Each has these common evidence columns: `grid`, `object_type`, `object_ref`, `name`, `data_representation`, `normalization_status`, `issues`, `extra_fields`. `data_representation` is `RAW_CONFIGURATION`. A common `name` cell remains empty when that field is not exposed by its object.

Object-specific columns use the exact selected field names listed above, except `name` is already common. `_ref` maps to `object_ref`. Both host sheets additionally expose `dhcp_configuration_status`. Structured columns contain JSON, while the following two sheets expose nested entries as individual rows:

| Sheet | Columns beyond the common evidence context |
| --- | --- |
| `Reservation_Options` | `option_field`, `option_index`, `option_name`, `code`, `vendor`, `user_class`, `option_type`, `stored_value`, `use_option`, `use_options`, `extra_fields` |
| `Reservation_Links` | `relationship_field`, `relationship_index`, `target`, `configured_rule_type`, `use_logic_filter_rules`, `relationship_data`, `interpretation` |

The context of these two sheets is `grid,object_type,object_ref,name,data_representation,normalization_status,issues`. Nested option mappings are `name -> option_name`, `num -> code`, `vendor_class -> vendor`, `value -> stored_value`; the collection field is recorded separately, including `ms_options`, `ipv6_options`, and nested host paths. Raw `use_*` flags remain separate from values. Link rows contain stored filter/host/Superhost relationships with unresolved target evidence.

Existing `Coverage`, `Grid_Summary`, `Errors`, and `Manual_Review` expose collection and interpretation status. Fixed-address effective evidence continues through the existing `DHCP_Effective` and `DHCP_Options` sheets. Other new objects are excluded from effective inference. The corrected live workbook has **zero data rows in all twelve object sheets and both nested-detail sheets**.

## Fixtures and validation

The [fixture provenance](../tests/fixtures/reservations_lab_20260920/provenance.json) contains SHA-256 hashes for **25 evidence files**, plus the provenance file itself:

- Twelve genuine runtime object schemas.
- Eleven genuine empty RAW response pages, one for each directly collected type.
- One genuine empty fixed-address effective page.
- One genuine HTTP 400 diagnostic proving the mandatory child-parent search parameter.

Fixtures preserve the first immutable capture byte-for-byte. The corrected capture independently confirms those empty inventories. No populated live fixture exists. Populated examples in the new tests are explicitly synthetic because these inventories are empty; parent/child synthetic scenarios use the complete empty parent evidence and are not presented as successful populated live validation.

Validation recorded in [validation_results.json](../output/reservations-20260920T065910Z/validation_results.json):

- Complete suite: `python -m pytest -q -p no:cacheprovider` -> **301 passed**.
- Tests cover runtime-readable field selection, pagination, parent/type scope, empty and failed queries, partial parents/pages, typed nested data, unknown fields, source indexes, conservative host/filter semantics, fixtures, and report/offline integration.
- Two network-blocked offline report builds have identical workbook sheet/cell matrices and identical Markdown bytes.
- Existing core and topology captures rebuild to identical workbook matrices and identical Markdown bytes.
- All archived files remain unchanged: core 17, topology 14, initial reservation capture 26, corrected reservation capture 26.
- Ten protected source files have unchanged SHA-256 hashes: `client.py`, `schema.py`, `storage.py`, `normalize.py`, `cli.py`, `config.py`, `analysis.py`, `models.py`, `topology.py`, and `collectors/topology.py`.
- `git diff --check` passes. Existing ignore rules continue to exclude local LAB configuration, `.env`, and live output. Fixture JSON attributes preserve captured bytes across line-ending conversion.

The immutable archive format remains version 1. No WAPI client, inheritance, storage, offline, topology, or general report architecture redesign was required. The known Member inheritance limitation remains accepted and unchanged.

## Files changed

| File | Change |
| --- | --- |
| `src/infoblox_inventory/collectors/core.py` | Adds bounded registry/aliases, schema capability checks and the child-parent dependency dispatch. |
| `src/infoblox_inventory/collectors/reservations.py` | New runtime-backed selections and per-parent child collection. |
| `src/infoblox_inventory/reservations.py` | New typed records, nested normalization, source indexes, coverage and Excel rows. |
| `src/infoblox_inventory/report.py` | Additive typed sheets, nested rows, coverage and scope notes. |
| `tests/test_reservation_collection.py` | Schema, paging, scope, parent dependency, error and replay tests. |
| `tests/test_reservation_normalization.py` | Explicitly synthetic typed/nested/semantic tests for empty LAB inventories. |
| `tests/test_reservation_report.py` | Workbook and fixture/report integration tests. |
| `tests/fixtures/reservations_lab_20260920/` | Twenty-five captured evidence files and SHA-256 provenance. |
| `.gitattributes` | Preserves bytes of new captured JSON fixtures. |
| `README.md` | New aliases, commands, scope and validation notes. |
| `docs/reservations-filters-increment.md` | This standalone implementation/evidence record. |

Generated live schemas, manifests, original responses, diagnostic helpers, logs and workbooks remain under ignored `output/reservations-20260920T065910Z/`. Reviewable source/fixture changes are left in the working tree.

## Unresolved semantics and limitations

- LAB has no populated reservation/filter objects. Runtime schemas, empty responses and the parent constraint are live evidence; populated shapes, policy configurations and multi-parent pagination are tested synthetically.
- `superhostchild` with an actual populated parent could not be validated live. Its parent/type strategy follows the real error and runtime search capabilities; no appliance object was created to manufacture evidence.
- Fixed-address `template`, and roaming-host `template`/`ipv6_template`, are write-only in the runtime schemas. Origin is not reconstructed. There is no direct readable NIOS member/failover field on fixed addresses; `ms_server` and cloud delegation remain the distinct structures actually exposed.
- Host IPv4 child references and Superhost union references are retained without resolving target semantics. Host context is not automatically a DHCP reservation. Roaming hosts have no inferred fixed IP.
- Filter names, expressions, relay matching fields, fingerprints and NAC data are configuration evidence. Consumer assignments outside this increment, permit/deny outcomes, and operational deployment are not inferred. `logic_filter_rules` preserves only the exposed filter/type/use information.
- `configure_for_dhcp` is readable but not searchable in the host IPv4 runtime schema; no guessed server-side boolean filter is used. Missing flags remain unresolved.
- Standalone IPv6 fixed-address/host/filter endpoints are exposed but deferred, not labeled unavailable. Selected IPv6 fields on the already-scoped `roaminghost` object remain stored evidence.
- Member inheritance remains limited as established by the validated baseline. RAW/effective reads are separate requests; neither snapshot atomicity nor effective policy is inferred.

## Appendix: all 39 executed request URLs

The safe log stores method, object path, timestamp and status, not full query strings. The URLs below are reconstructed from that ordered log, saved query parameters, and the unchanged client/helper request construction. They represent the requests executed, including the failed child requests, without authorization headers, credentials or cookies. Query parameter order and percent encoding follow `requests.Request.prepare()`; timestamps are the log's local wall-clock values. No new network request was made to prepare this appendix.

| # | Logged time | Phase | HTTP | GET URL |
| ---: | --- | --- | ---: | --- |
| 1 | 2026-09-20 09:40:04,242 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/?_schema=1` |
| 2 | 2026-09-20 09:40:04,320 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/fixedaddress?_schema=1&_schema_version=2&_schema_searchable=1` |
| 3 | 2026-09-20 09:40:04,403 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/filtermac?_schema=1&_schema_version=2&_schema_searchable=1` |
| 4 | 2026-09-20 09:40:04,473 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/macfilteraddress?_schema=1&_schema_version=2&_schema_searchable=1` |
| 5 | 2026-09-20 09:40:04,604 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/filteroption?_schema=1&_schema_version=2&_schema_searchable=1` |
| 6 | 2026-09-20 09:40:04,683 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/filterrelayagent?_schema=1&_schema_version=2&_schema_searchable=1` |
| 7 | 2026-09-20 09:40:04,750 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/filterfingerprint?_schema=1&_schema_version=2&_schema_searchable=1` |
| 8 | 2026-09-20 09:40:04,811 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/filternac?_schema=1&_schema_version=2&_schema_searchable=1` |
| 9 | 2026-09-20 09:40:04,888 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/record:host?_schema=1&_schema_version=2&_schema_searchable=1` |
| 10 | 2026-09-20 09:40:04,991 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/record:host_ipv4addr?_schema=1&_schema_version=2&_schema_searchable=1` |
| 11 | 2026-09-20 09:40:05,092 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/roaminghost?_schema=1&_schema_version=2&_schema_searchable=1` |
| 12 | 2026-09-20 09:40:05,221 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/superhost?_schema=1&_schema_version=2&_schema_searchable=1` |
| 13 | 2026-09-20 09:40:05,354 | Schema | 200 | `https://192.168.88.243/wapi/v2.13.7/superhostchild?_schema=1&_schema_version=2&_schema_searchable=1` |
| 14 | 2026-09-20 09:45:38,820 | Initial raw | 200 | `https://192.168.88.243/wapi/v2.13.7/fixedaddress?_max_results=1000&_return_fields=ipv4addr%2Cmac%2Cdhcp_client_identifier%2Cclient_identifier_prepend_zero%2Cname%2Cnetwork%2Cnetwork_view%2Cmatch_client%2Cagent_circuit_id%2Cagent_remote_id%2Cenable_ddns%2Cddns_hostname%2Cddns_domainname%2Coptions%2Cms_options%2Cms_server%2Ccloud_info%2Ccomment%2Cextattrs%2Cdisable%2Cis_invalid_mac%2Creserved_interface%2Clogic_filter_rules%2Cignore_dhcp_option_list_request%2Cbootfile%2Cbootserver%2Cnextserver%2Cdeny_bootp%2Cenable_pxe_lease_time%2Cpxe_lease_time%2Cuse_enable_ddns%2Cuse_ddns_domainname%2Cuse_options%2Cuse_ms_options%2Cuse_logic_filter_rules%2Cuse_ignore_dhcp_option_list_request%2Cuse_bootfile%2Cuse_bootserver%2Cuse_nextserver%2Cuse_deny_bootp%2Cuse_pxe_lease_time&_paging=1&_return_as_object=1` |
| 15 | 2026-09-20 09:45:38,913 | Initial effective | 200 | `https://192.168.88.243/wapi/v2.13.7/fixedaddress?_max_results=1000&_return_fields=ipv4addr%2Cmac%2Cdhcp_client_identifier%2Cclient_identifier_prepend_zero%2Cname%2Cnetwork%2Cnetwork_view%2Cmatch_client%2Cagent_circuit_id%2Cagent_remote_id%2Cenable_ddns%2Cddns_hostname%2Cddns_domainname%2Coptions%2Cms_options%2Cms_server%2Ccloud_info%2Ccomment%2Cextattrs%2Cdisable%2Cis_invalid_mac%2Creserved_interface%2Clogic_filter_rules%2Cignore_dhcp_option_list_request%2Cbootfile%2Cbootserver%2Cnextserver%2Cdeny_bootp%2Cenable_pxe_lease_time%2Cpxe_lease_time%2Cuse_enable_ddns%2Cuse_ddns_domainname%2Cuse_options%2Cuse_ms_options%2Cuse_logic_filter_rules%2Cuse_ignore_dhcp_option_list_request%2Cuse_bootfile%2Cuse_bootserver%2Cuse_nextserver%2Cuse_deny_bootp%2Cuse_pxe_lease_time&_inheritance=True&_paging=1&_return_as_object=1` |
| 16 | 2026-09-20 09:45:38,991 | Initial raw | 200 | `https://192.168.88.243/wapi/v2.13.7/record:host?_max_results=1000&_return_fields=name%2Cnetwork_view%2Cdisable%2Ccomment%2Cextattrs%2Cipv4addrs&_paging=1&_return_as_object=1` |
| 17 | 2026-09-20 09:45:39,073 | Initial raw | 200 | `https://192.168.88.243/wapi/v2.13.7/record:host_ipv4addr?_max_results=1000&_return_fields=ipv4addr%2Cmac%2Chost%2Cnetwork%2Cnetwork_view%2Cconfigure_for_dhcp%2Cmatch_client%2Coptions%2Clogic_filter_rules%2Cis_invalid_mac%2Creserved_interface%2Cignore_client_requested_options%2Cbootfile%2Cbootserver%2Cnextserver%2Cdeny_bootp%2Cenable_pxe_lease_time%2Cpxe_lease_time%2Cuse_options%2Cuse_logic_filter_rules%2Cuse_ignore_client_requested_options%2Cuse_bootfile%2Cuse_bootserver%2Cuse_nextserver%2Cuse_deny_bootp%2Cuse_pxe_lease_time&_paging=1&_return_as_object=1` |
| 18 | 2026-09-20 09:45:39,149 | Initial raw | 200 | `https://192.168.88.243/wapi/v2.13.7/roaminghost?_max_results=1000&_return_fields=name%2Caddress_type%2Cmac%2Cdhcp_client_identifier%2Cclient_identifier_prepend_zero%2Cmatch_client%2Cnetwork_view%2Cenable_ddns%2Cddns_hostname%2Cddns_domainname%2Cforce_roaming_hostname%2Coptions%2Ccomment%2Cextattrs%2Cdisable%2Cignore_dhcp_option_list_request%2Cipv6_duid%2Cipv6_mac_address%2Cipv6_match_option%2Cipv6_options%2Cpreferred_lifetime%2Cvalid_lifetime%2Cbootfile%2Cbootserver%2Cnextserver%2Cdeny_bootp%2Cenable_pxe_lease_time%2Cpxe_lease_time%2Cuse_enable_ddns%2Cuse_ddns_domainname%2Cuse_options%2Cuse_ignore_dhcp_option_list_request%2Cuse_ipv6_options%2Cuse_preferred_lifetime%2Cuse_valid_lifetime%2Cuse_bootfile%2Cuse_bootserver%2Cuse_nextserver%2Cuse_deny_bootp%2Cuse_pxe_lease_time&_paging=1&_return_as_object=1` |
| 19 | 2026-09-20 09:45:39,231 | Initial raw | 200 | `https://192.168.88.243/wapi/v2.13.7/superhost?_max_results=1000&_return_fields=name%2Ccomment%2Cdisabled%2Cdhcp_associated_objects&_paging=1&_return_as_object=1` |
| 20 | 2026-09-20 09:45:39,313 | Initial raw | 400 | `https://192.168.88.243/wapi/v2.13.7/superhostchild?_max_results=1000&_return_fields=name%2Ccomment%2Cdata%2Cdisabled%2Cnetwork_view%2Cparent%2Crecord_parent%2Ctype%2Cassociated_object&type=FixedAddress&_paging=1&_return_as_object=1` |
| 21 | 2026-09-20 09:45:39,383 | Initial raw | 200 | `https://192.168.88.243/wapi/v2.13.7/filtermac?_max_results=1000&_return_fields=name%2Ccomment%2Cdisable%2Cdefault_mac_address_expiration%2Cenforce_expiration_times%2Cnever_expires%2Clease_time%2Coptions&_paging=1&_return_as_object=1` |
| 22 | 2026-09-20 09:45:39,467 | Initial raw | 200 | `https://192.168.88.243/wapi/v2.13.7/macfilteraddress?_max_results=1000&_return_fields=mac%2Cfilter%2Ccomment%2Cauthentication_time%2Cexpiration_time%2Cnever_expires%2Cfingerprint%2Cis_registered_user&_paging=1&_return_as_object=1` |
| 23 | 2026-09-20 09:45:39,574 | Initial raw | 200 | `https://192.168.88.243/wapi/v2.13.7/filteroption?_max_results=1000&_return_fields=name%2Ccomment%2Cexpression%2Capply_as_class%2Coption_space%2Coption_list%2Clease_time%2Cbootfile%2Cbootserver%2Cnext_server%2Cpxe_lease_time&_paging=1&_return_as_object=1` |
| 24 | 2026-09-20 09:45:39,649 | Initial raw | 200 | `https://192.168.88.243/wapi/v2.13.7/filterrelayagent?_max_results=1000&_return_fields=name%2Ccomment%2Cis_circuit_id%2Ccircuit_id_name%2Cis_circuit_id_substring%2Ccircuit_id_substring_offset%2Ccircuit_id_substring_length%2Cis_remote_id%2Cremote_id_name%2Cis_remote_id_substring%2Cremote_id_substring_offset%2Cremote_id_substring_length&_paging=1&_return_as_object=1` |
| 25 | 2026-09-20 09:45:39,716 | Initial raw | 200 | `https://192.168.88.243/wapi/v2.13.7/filterfingerprint?_max_results=1000&_return_fields=name%2Ccomment%2Cfingerprint&_paging=1&_return_as_object=1` |
| 26 | 2026-09-20 09:45:39,808 | Initial raw | 200 | `https://192.168.88.243/wapi/v2.13.7/filternac?_max_results=1000&_return_fields=name%2Ccomment%2Cexpression%2Clease_time%2Coptions&_paging=1&_return_as_object=1` |
| 27 | 2026-09-20 09:48:03,548 | Diagnostic | 400 | `https://192.168.88.243/wapi/v2.13.7/superhostchild?_return_fields=name%2Ccomment%2Cdata%2Cdisabled%2Cnetwork_view%2Cparent%2Crecord_parent%2Ctype%2Cassociated_object&_paging=1&_return_as_object=1&_max_results=1000&type=FixedAddress` |
| 28 | 2026-09-20 14:13:19,172 | Corrected raw | 200 | `https://192.168.88.243/wapi/v2.13.7/fixedaddress?_max_results=1000&_return_fields=ipv4addr%2Cmac%2Cdhcp_client_identifier%2Cclient_identifier_prepend_zero%2Cname%2Cnetwork%2Cnetwork_view%2Cmatch_client%2Cagent_circuit_id%2Cagent_remote_id%2Cenable_ddns%2Cddns_hostname%2Cddns_domainname%2Coptions%2Cms_options%2Cms_server%2Ccloud_info%2Ccomment%2Cextattrs%2Cdisable%2Cis_invalid_mac%2Creserved_interface%2Clogic_filter_rules%2Cignore_dhcp_option_list_request%2Cbootfile%2Cbootserver%2Cnextserver%2Cdeny_bootp%2Cenable_pxe_lease_time%2Cpxe_lease_time%2Cuse_enable_ddns%2Cuse_ddns_domainname%2Cuse_options%2Cuse_ms_options%2Cuse_logic_filter_rules%2Cuse_ignore_dhcp_option_list_request%2Cuse_bootfile%2Cuse_bootserver%2Cuse_nextserver%2Cuse_deny_bootp%2Cuse_pxe_lease_time&_paging=1&_return_as_object=1` |
| 29 | 2026-09-20 14:13:19,231 | Corrected effective | 200 | `https://192.168.88.243/wapi/v2.13.7/fixedaddress?_max_results=1000&_return_fields=ipv4addr%2Cmac%2Cdhcp_client_identifier%2Cclient_identifier_prepend_zero%2Cname%2Cnetwork%2Cnetwork_view%2Cmatch_client%2Cagent_circuit_id%2Cagent_remote_id%2Cenable_ddns%2Cddns_hostname%2Cddns_domainname%2Coptions%2Cms_options%2Cms_server%2Ccloud_info%2Ccomment%2Cextattrs%2Cdisable%2Cis_invalid_mac%2Creserved_interface%2Clogic_filter_rules%2Cignore_dhcp_option_list_request%2Cbootfile%2Cbootserver%2Cnextserver%2Cdeny_bootp%2Cenable_pxe_lease_time%2Cpxe_lease_time%2Cuse_enable_ddns%2Cuse_ddns_domainname%2Cuse_options%2Cuse_ms_options%2Cuse_logic_filter_rules%2Cuse_ignore_dhcp_option_list_request%2Cuse_bootfile%2Cuse_bootserver%2Cuse_nextserver%2Cuse_deny_bootp%2Cuse_pxe_lease_time&_inheritance=True&_paging=1&_return_as_object=1` |
| 30 | 2026-09-20 14:13:19,283 | Corrected raw | 200 | `https://192.168.88.243/wapi/v2.13.7/record:host?_max_results=1000&_return_fields=name%2Cnetwork_view%2Cdisable%2Ccomment%2Cextattrs%2Cipv4addrs&_paging=1&_return_as_object=1` |
| 31 | 2026-09-20 14:13:19,404 | Corrected raw | 200 | `https://192.168.88.243/wapi/v2.13.7/record:host_ipv4addr?_max_results=1000&_return_fields=ipv4addr%2Cmac%2Chost%2Cnetwork%2Cnetwork_view%2Cconfigure_for_dhcp%2Cmatch_client%2Coptions%2Clogic_filter_rules%2Cis_invalid_mac%2Creserved_interface%2Cignore_client_requested_options%2Cbootfile%2Cbootserver%2Cnextserver%2Cdeny_bootp%2Cenable_pxe_lease_time%2Cpxe_lease_time%2Cuse_options%2Cuse_logic_filter_rules%2Cuse_ignore_client_requested_options%2Cuse_bootfile%2Cuse_bootserver%2Cuse_nextserver%2Cuse_deny_bootp%2Cuse_pxe_lease_time&_paging=1&_return_as_object=1` |
| 32 | 2026-09-20 14:13:19,473 | Corrected raw | 200 | `https://192.168.88.243/wapi/v2.13.7/roaminghost?_max_results=1000&_return_fields=name%2Caddress_type%2Cmac%2Cdhcp_client_identifier%2Cclient_identifier_prepend_zero%2Cmatch_client%2Cnetwork_view%2Cenable_ddns%2Cddns_hostname%2Cddns_domainname%2Cforce_roaming_hostname%2Coptions%2Ccomment%2Cextattrs%2Cdisable%2Cignore_dhcp_option_list_request%2Cipv6_duid%2Cipv6_mac_address%2Cipv6_match_option%2Cipv6_options%2Cpreferred_lifetime%2Cvalid_lifetime%2Cbootfile%2Cbootserver%2Cnextserver%2Cdeny_bootp%2Cenable_pxe_lease_time%2Cpxe_lease_time%2Cuse_enable_ddns%2Cuse_ddns_domainname%2Cuse_options%2Cuse_ignore_dhcp_option_list_request%2Cuse_ipv6_options%2Cuse_preferred_lifetime%2Cuse_valid_lifetime%2Cuse_bootfile%2Cuse_bootserver%2Cuse_nextserver%2Cuse_deny_bootp%2Cuse_pxe_lease_time&_paging=1&_return_as_object=1` |
| 33 | 2026-09-20 14:13:19,550 | Corrected raw | 200 | `https://192.168.88.243/wapi/v2.13.7/superhost?_max_results=1000&_return_fields=name%2Ccomment%2Cdisabled%2Cdhcp_associated_objects&_paging=1&_return_as_object=1` |
| 34 | 2026-09-20 14:13:19,701 | Corrected raw | 200 | `https://192.168.88.243/wapi/v2.13.7/filtermac?_max_results=1000&_return_fields=name%2Ccomment%2Cdisable%2Cdefault_mac_address_expiration%2Cenforce_expiration_times%2Cnever_expires%2Clease_time%2Coptions&_paging=1&_return_as_object=1` |
| 35 | 2026-09-20 14:13:19,815 | Corrected raw | 200 | `https://192.168.88.243/wapi/v2.13.7/macfilteraddress?_max_results=1000&_return_fields=mac%2Cfilter%2Ccomment%2Cauthentication_time%2Cexpiration_time%2Cnever_expires%2Cfingerprint%2Cis_registered_user&_paging=1&_return_as_object=1` |
| 36 | 2026-09-20 14:13:19,870 | Corrected raw | 200 | `https://192.168.88.243/wapi/v2.13.7/filteroption?_max_results=1000&_return_fields=name%2Ccomment%2Cexpression%2Capply_as_class%2Coption_space%2Coption_list%2Clease_time%2Cbootfile%2Cbootserver%2Cnext_server%2Cpxe_lease_time&_paging=1&_return_as_object=1` |
| 37 | 2026-09-20 14:13:19,942 | Corrected raw | 200 | `https://192.168.88.243/wapi/v2.13.7/filterrelayagent?_max_results=1000&_return_fields=name%2Ccomment%2Cis_circuit_id%2Ccircuit_id_name%2Cis_circuit_id_substring%2Ccircuit_id_substring_offset%2Ccircuit_id_substring_length%2Cis_remote_id%2Cremote_id_name%2Cis_remote_id_substring%2Cremote_id_substring_offset%2Cremote_id_substring_length&_paging=1&_return_as_object=1` |
| 38 | 2026-09-20 14:13:19,992 | Corrected raw | 200 | `https://192.168.88.243/wapi/v2.13.7/filterfingerprint?_max_results=1000&_return_fields=name%2Ccomment%2Cfingerprint&_paging=1&_return_as_object=1` |
| 39 | 2026-09-20 14:13:20,045 | Corrected raw | 200 | `https://192.168.88.243/wapi/v2.13.7/filternac?_max_results=1000&_return_fields=name%2Ccomment%2Cexpression%2Clease_time%2Coptions&_paging=1&_return_as_object=1` |

The corrected child request form above is deliberately absent from this execution table: there were no parents to query. No live continuation requests, mutation requests, redirects or function calls were made.

# Infoblox Current-State Inventory

A read-only Python 3.11+ assessment collector for independent Infoblox NIOS Grids. It gathers evidence for current-state assessment and does not change objects, DHCP services, or Grid configuration. All appliance requests use `requests.Session` and HTTP GET.

## Install and configure

```powershell
python -m pip install -e ".[test]"
```

Copy `config/grids.example.yaml` to your private configuration and replace the example URLs. Each Grid may supply `username` and `password_env`, which names an environment variable containing its password. If the password variable is absent, the CLI uses a hidden `getpass` prompt. If the terminal cannot disable echo, prompting fails before reading a password; use the configured environment variable instead. The default shared variables are `INFOBLOX_USER` and `INFOBLOX_PASSWORD`. Password values are rejected in YAML, are not accepted as CLI arguments, and must not be typed into command history.

Use HTTPS with certificate verification in production; `ca_bundle` accepts a corporate CA bundle path. `--insecure` (also `--no-verify-tls`) disables verification for lab/testing and emits a warning. `--verify-tls` enables verification, retaining a configured CA bundle.

The compatibility baseline is **WAPI 2.13.7**, including for NIOS 9.0.7 production. Root schema discovery verifies the configured version and caches it; advertising 2.14 never triggers an automatic upgrade. Legacy `wapi_version: auto` also tries only 2.13.7. A different version requires explicit configuration. Grid URLs are HTTPS origins, such as `https://grid-a.example.com`; the client appends `/wapi/v2.13.7/`.

## Collect once, work offline

```powershell
# Read the root schema to check authentication and version support.
python -m infoblox_inventory --config config/grids.yaml --grid JB --test-connection

# Save raw and effective responses without generating reports.
python -m infoblox_inventory --config config/grids.yaml --all --collect-raw-only --output-dir output/run-001

# Analyze the saved archive without credentials or network requests.
python -m infoblox_inventory --offline output/run-001/raw --output-dir output/report-001

# Or collect and generate reports in one run.
python -m infoblox_inventory --config config/grids.yaml --all --output-dir output/run-002
```

`--fixture` is an alias for `--offline`. Replay accepts a run directory, its `raw` directory, or a single Grid archive directory; `--grid` can narrow it. Connection testing does not prove object-level read permissions. Live collection errors return exit code 1, retain completed pages, and appear in coverage/errors. An existing raw Grid directory is refused: choose a fresh run output directory so evidence from separate runs cannot be mixed or overwritten.

Focused collectors include `--collector networks`, `ranges`, `members`, `options`, `templates`, `topology`, `reservations`, `reservations_filters`, `filters`, and any object name listed by `--help`. The `options` alias collects Grid DHCP, Member DHCP, Networks, Ranges, and Fixed Addresses. The `members` alias includes both related registered object types; `filters` selects six filter and MAC-entry types; `templates` selects network, range and fixed-address templates.

For controlled lab validation, `--collector core` selects only Network Views, Grid DHCP, Members, Member DHCP, Networks, and Ranges. `config/grids.lab.yaml` pins the existing lab to WAPI 2.13.7 and stores no password; use `--insecure` only for this lab. `--log-level DEBUG` records GET methods and object paths without credentials, query tokens, or response bodies.

`--collector topology` selects only `dhcpfailover`, `networktemplate`, `rangetemplate`, `fixedaddresstemplate`, `dhcpoptionspace`, and `dhcpoptiondefinition`. Their readable fields were verified against runtime LAB WAPI 2.13.7 schemas. They use the existing paginated RAW archive and offline workflow:

```powershell
python -m infoblox_inventory --config config/grids.lab.yaml --grid LAB-GRID --collector topology --collect-raw-only --insecure --output-dir output/topology-001
python -m infoblox_inventory --offline output/topology-001/raw --output-dir output/topology-report-001
```

Six typed inventory sheets and `Template_Options` expose stored configuration, observed use flags, associations and unknown fields. These rows are labeled `RAW_CONFIGURATION`; they do not resolve template inheritance. See [the topology increment](docs/topology-increment.md) for exact fields, live GETs, counts and limitations. The captured LAB contains one option space and 95 definitions; failover and template inventories are genuinely empty. Populated examples for those types are explicitly synthetic tests.

`--collector reservations_filters` selects DHCP fixed addresses, IPv4 host DHCP context, roaming hosts, Superhost DHCP relationships and the six MAC/option/relay/fingerprint/NAC filter objects. `reservations` selects the six reservation/context types; `filters` selects all six filter types, including MAC entries. `fixed_addresses` remains limited to `fixedaddress`.

```powershell
python -m infoblox_inventory --config config/grids.lab.yaml --grid LAB-GRID --collector reservations_filters --collect-raw-only --insecure --output-dir output/reservations-001
python -m infoblox_inventory --offline output/reservations-001/raw --output-dir output/reservations-report-001
```

Twelve typed sheets plus `Reservation_Options` and `Reservation_Links` expose stored fields, nested data, refs and source indexes. Fixed-address effective values still use the existing inheritance pipeline. Host DHCP status describes explicit IPv4 flags only; filter names do not imply permit/deny policy. DDNS and EA fields are retained only as reservation metadata. No general DNS records, DDNS module or EA module is added. [The reservation/filter increment](docs/reservations-filters-increment.md) records the exact runtime fields, live requests, fixtures and limitations.

The LAB requires `parent` for `superhostchild`, although its schema does not mark it mandatory. The collector discovers Superhost names first and paginates `type=FixedAddress&parent=<observed-name>` for each one. Version-1 manifests retain one child query with optional `subqueries` metadata recording each actual request and its pages. Complete empty parent discovery yields `EMPTY` with no child GET or fabricated response; incomplete parents or failed reads remain partial/error. Selecting `superhostchild` also collects its `superhost` dependency.

## Evidence and inheritance

The existing modules keep live collection, raw persistence, normalization, comparison, and reporting separate. The collector reads root/object schemas once per client, selects bounded readable fields, and derives `use_*` relationships from schema `overridden_by`. Unsupported fields/objects are recorded explicitly. Schema failures do not cause an unbounded all-fields query.

Raw pages are stored under:

```text
output/run-001/raw/<Grid>/
    manifest.json
    schema/root.json
    schema/<object>.json
    <object>/raw/page-000001.json
    <object>/effective/page-000001.json
```

Path components are encoded for Windows compatibility (for example `member%3Adhcpproperties`). The manifest records the collection timestamp, version, query parameters, page paths, errors, and coverage. Files retain the decoded JSON content of responses, including paging envelopes and unknown fields; whitespace and byte formatting are not preserved. Report generation never modifies saved responses. An interrupted or failed query remains partial on replay.

Member DHCP, Network, Range, and Fixed Address collection requests both plain GET and `_inheritance=True` when the schema exposes relevant override metadata. Grid DHCP is the root configuration. Other existing collectors currently save plain responses only. Requests are paginated in bulk, with finite GET retries, timeouts, redirect refusal, and sanitized errors. Logging includes Grid, object, page, record count, and elapsed time without credentials or HTTP response bodies.

A plain child GET can contain a shadow/default value while its `use_*` flag is false. It is never substituted for an effective value. Scalar wrappers retain `inherited`, `multisource`, `source`, and `value`. Effective options follow their outer source group, including inherited options with inner `use_option=false`; the collector does not reimplement WAPI's option merge. Local empty-source wrappers resolve to the queried object. `NOT_DEFINED` means `NOT_CONFIGURED`. Multiple sources remain preserved without selecting one. Unwrapped or insufficient effective evidence remains unresolved.

## Outputs and coverage

Reports include `current_state_inventory.xlsx`, `current_state_summary.md`, and `manual_review.md`. The workbook retains filters, freeze panes, readable widths, object inventories, and coverage, with separate DHCP raw, effective scalar, and option information. Source refs are retained alongside human-readable source levels and objects. Nested values are serialized for Excel, and values resembling formulas are written as literal text.

Coverage distinguishes `COMPLETE`, `PARTIAL`, `EMPTY`, `MANUAL_REVIEW_REQUIRED`, `NOT_EXPOSED_BY_WAPI`, and `ERROR`; normalized field status also distinguishes `NOT_CONFIGURED`. Coverage is recorded per object/query and unsupported field. A completed query does not imply that every assessment area is covered. Approval workflows and documentation requirements always need manual confirmation. Commonly observed values are descriptive evidence, not approved standards or Grid rankings.

## Tests and remaining work

```powershell
python -m pytest -q
```

The original fixtures under `tests/fixtures` reconstruct the supplied lab observations. `tests/fixtures/live_lab_20260920` additionally contains byte-identical responses from the authorized NIOS 9.1.0 lab collection, with source paths and SHA-256 provenance. Tests cover scalar/local/parent provenance, `NOT_DEFINED`, mixed Grid/Member/Network/Range options, the 43200 raw versus 28800 effective lease regression, schema parsing, pagination, persistence, and offline replay. Synthetic multisource examples test lossless preservation only, not an asserted NIOS response format.

The live lab returned Network/Range inheritance wrappers as expected, including Network lease 28800 despite raw 43200 and the Range's four distinct option sources. Its bulk Member DHCP query returned plain fields even with `_inheritance=True`; those Member effective values remain `PARTIAL` and are never reconstructed from parent values. Range ref suffixes use `start/end/view`; display labels normalize the address pair to `start-end` while preserving the original ref. Some scalar wrappers identify a Grid source but omit `value`; these remain unresolved, separately from explicit `NOT_DEFINED`.

To validate a fresh saved lab run without any network access, run `python scripts/validate_lab_snapshot.py <run-directory>`. The utility checks expected values and associations, reads the workbook, moves the first generated reports aside, rebuilds them with network entrypoints blocked, and compares results and raw-file hashes. It refuses existing validation/report outputs.

No live lab or production access is required for these tests. NIOS 9.1 lab evidence remains an approximation for NIOS 9.0.7; verify the saved response formats and read-only service-account permissions with a controlled integration run before production rollout. Raw and effective collection are separate GETs, not an atomic appliance snapshot.

The topology increment adds reusable DHCP objects only. Fixed-address objects, filters, DNS, DDNS and Extensible Attributes are not extended by it. Cross-Grid analysis remains a limited descriptive comparison of comparable resolved options; it does not establish object correspondence across differing site structures or exhaustively compare scalars, filters, templates and EAs. Further scope requires a separate increment backed by runtime schemas and response evidence.

The subsequent reservation/filter increment was validated with **301 tests**. All eleven directly collected LAB object types are empty; Superhost children are absent by complete empty parent discovery. Populated behavior uses explicitly synthetic fixtures only for these empty inventories; no populated live validation is claimed. Twelve genuine schemas, twelve successful empty response pages (including fixed-address effective), and the real parent-required HTTP400 diagnostic are preserved with SHA-256 provenance. IPv6 fixed-address/host endpoints and consumers outside this increment remain deferred.

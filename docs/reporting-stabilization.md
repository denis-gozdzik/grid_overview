# Reporting, client and fixture stabilization

This increment completes implementation steps 1–8 from the reporting repair request.
It extends the reservation/filter baseline (`db95d64`) without adding collectors or
changing the WAPI inheritance algorithm, RAW storage version, or Superhost dependency
handling. No live Infoblox requests were executed for this increment. All appliance
access remains GET-only.

## Excel corruption and repair

The shared writer in `report.py` set a worksheet-level AutoFilter and also created an
Excel Table over the same range. The table XML already owned an AutoFilter. The saved
core workbook contained fourteen such overlaps, including Grid_Summary, Coverage and
Manual_Review.

The common `_write_inventory_sheet` helper now creates table-owned filters only.
Header-only inventories have neither a table nor a filter. Display headers are
nonempty strings, unique ignoring case; repairing a display label never changes its
source-key mapping or loses a value. Untrusted WAPI text remains literal Excel text.

`xlsx_validation.py` reads the actual ZIP/XML package independently of openpyxl. It
checks ZIP CRCs, workbook/worksheet/table relationships and targets, duplicate/orphan
parts, table IDs and names, valid rectangular refs, actual data rows, header types and
uniqueness, tableColumn counts and widths, matching cell/header names, and overlapping
worksheet filters. Regression tests include 24 deliberately corrupted packages.

The old workbook is rejected with `Worksheet AutoFilter overlaps Excel Table:
Grid_Summary`. The corrected cumulative workbook passes the structural checks,
openpyxl reload, and `unzip -t`. Installed Microsoft Excel **16.0** opened it normally,
read-only, with **38 worksheets and 18 tables**. No repair/recovery mode was requested.
The workbook hash stayed unchanged after Excel closed. Excel also exported Overview
to PDF; all four rendered pages were checked for legibility and clipped content.
LibreOffice was not available. The corporate workbook itself was not present in this
workspace, so this check uses the existing home LAB evidence.

## Cumulative reporting and Overview

`--all` remains the live CLI option. A real-client/real-collector regression with
mocked GET transport verifies that one `--all` run collects and reports networks,
templates/options, fixed addresses and filters together, including pagination.

Repeatable `--offline` inputs additionally combine previously collected increments
through `dataset.combine_collections`, before normalization. No workbook concatenation
or RAW rewrite occurs. Each Grid has one cumulative model; RAW/effective/schema data
for an object form an indivisible snapshot. Identical bundles deduplicate; conflicting
object data, split RAW/effective snapshots, origins or WAPI versions are rejected.
Real partial/error coverage remains visible. Only redundant generic increment-scope
placeholders are removed when an explicit observation covers the same area.

`Collection_Sources` records Grid, Object, Collected At, WAPI Version, Raw Count and
Effective Count, including objects known only from failure/schema coverage. Combining
captures does not claim an atomic appliance snapshot. Input order does not change the
result, and inputs are deep-copied.

Overview is the first sheet. Its columns are Grid, Section, Metric, Observed value,
and Evidence / scope. It shows collection timestamps, WAPI version, errors, total RAW
object rows, networks, ranges, members, fixed addresses, explicitly DHCP-configured
host IPv4 entries, filter definitions, MAC entries, templates, option definitions,
coverage status counts, and manual-review counts. Related host objects are not claimed
to be unique reservations. Absent, failed and incomplete inventories remain explicit.

Effective DHCP summaries cover lease time, DNS, domain/search, router, nextserver,
boot/PXE and already-normalized DDNS values. They count confirmed observed values and
retain inherited/configured-here, unresolved and NOT_CONFIGURED counts. Vendor option
spaces stay separate. Unknown and multisource values are excluded from confirmed
summaries; no RAW fallback or local inheritance reconstruction is introduced.

The real LAB lease summary is **28800 (2), 3600 (1)** with one unresolved Member row.
The network's RAW **43200** remains in DHCP_Raw/DHCP_Options and is not substituted for
its effective **28800**. PXE lease time has its own clearly labeled parameter.

## Offline validation dataset and row counts

The final report combines these existing ignored RAW archives:

- `output/lab-live-20260920T060623Z/raw`
- `output/topology-20260920T062102Z/raw`
- `output/reservations-20260920T065910Z/corrected/raw`

Final workbook: `output/report-repair-20260921/final/current_state_inventory.xlsx`.
Machine-readable evidence: `validation.json` and `excel_validation.json` in that
directory. Two rebuilds with HTTP and socket connection entry points blocked produced
identical Excel cell matrices and Markdown. All **57 RAW files** remained byte-identical.
There are **102 RAW object rows across 24 object types**, with zero collection errors.

| Sheet | Data rows |
| --- | ---: |
| Overview | 42 |
| Grid_Summary | 24 |
| Coverage | 51 |
| Errors | 0 |
| DHCP_Effective | 49 |
| DHCP_Options | 14 |
| DHCP_Raw | 4 |
| Differences | 12 |
| Naming_Analysis | 65 |
| Manual_Review | 2 |
| Collection_Sources | 24 |
| Option_Definitions | 95 |
| Option_Spaces | 1 |
| Grid_DHCP | 1 |
| Members_Failover | 1 |
| Member_DHCP | 1 |
| Networks | 1 |
| Network_Views | 1 |
| Ranges | 1 |

The remaining nineteen sheets have zero data rows and meaningful headers:
DHCP_Failover, Fingerprint_Filters, MAC_Filters, NAC_Filters, Option_Filters,
Relay_Agent_Filters, Fixed_Reservations, Fixed_Address_Templates, MAC_Filter_Addresses,
Network_Templates, Range_Templates, Host_DHCP_Context, Host_IPv4_DHCP, Roaming_Hosts,
Superhost_DHCP, Superhost_Fixed_Links, Reservation_Options, Reservation_Links and
Template_Options. Empty LAB inventories are not populated with synthetic report rows.

## HTTP and WAPI URL audit

The current client already handles HTTP failure before parsing success JSON and uses
a keyword-only `status_code`, so the reported historical HTTP400/multiple-argument
bugs did not reproduce in this baseline. It already normalizes both `2.13.7` and
`v2.13.7` to `/wapi/v2.13.7/`; that logic was retained.

One real gap was fixed: invalid JSON on a successful HTTP response now retains the
known HTTP status. Twenty-one added regressions cover HTTP 400/401/403/404/500/503/504,
status propagation through discovery, success JSON failures, connection errors and
Timeout/ReadTimeout/ConnectTimeout, sanitized error/log output, and both version forms.
Server error bodies and transport exception details are omitted from messages so
credentials or sensitive echoed query values cannot leak. GET-only bounded retries
and redirect refusal remain unchanged.

## Cross-platform fixture bytes and Git

All **49 existing evidence SHA-256 values** still match original provenance. Expected
hashes and captured data were not recalculated or edited. The core LAB tree lacked
`-text` protection; it now has the same protection as topology and reservations.

Nineteen previously committed files had normalized LF blobs while their working copies
retained original CRLF bytes: all thirteen core LAB JSON files (including provenance)
and the six topology schemas. Their file timestamps were refreshed so Git notices the
authentic byte differences. These large-looking fixture diffs are line-ending-only;
`git diff --ignore-space-at-eol -- tests/fixtures` has no content changes.

Before committing, include the exact protected paths:

```powershell
git add --renormalize -- tests/fixtures/live_lab_20260920 tests/fixtures/topology_lab_20260920
```

The project index was not staged by this work. New tests copy all three captured trees
and attributes into isolated temporary Git repositories, disable global/system Git
configuration and attributes, and exercise clean/forced checkout under Windows and
Linux newline settings. All evidence hashes, provenance bytes and explicit LF/CRLF
probes survive both configurations. Local configuration, credentials, certificates and
RAW/report output remain ignored; no corporate evidence was added to fixtures.

## Tests, changed files and next increment

Full-suite gates: **301 baseline → 328 Excel → 342 cumulative → 356 Overview → 377
client → 379 final**. The cumulative provenance regression was added before the Overview
gate. New suites contain 27 OOXML, 15 cumulative, 13 Overview, 21 client/error and two
Git-byte tests. Existing report assertions now expect table-owned filtering.

Implementation changes: `report.py`, `cli.py`, `client.py`, `models.py`; new `dataset.py`,
`overview.py`, `xlsx_validation.py`, and `scripts/validate_report_package.py`.
Supporting changes: README, `.gitattributes`, this document, three existing report test
files, five new test files, and the nineteen original-byte fixture restorations above.

The known Member inheritance limitation remains: plain responses do not prove effective
values and stay PARTIAL/null. Superhost children still require observed parents, preserve
page/parent ownership, continue after failures, and create no invented empty responses.
Template origin/write-only relationships and unproven policy semantics remain unresolved.

No new DDNS, EA or DNS collector was implemented, and cross-Grid Differences/naming
analysis were not expanded. This is a completed stabilization stage, not a claim that
Task-1 coverage is complete. Next: a bounded DDNS increment backed by runtime readable
fields and real response shapes, followed by EA, limited DHCP-adjacent DNS assessment
and richer descriptive cross-Grid comparisons. Continue to avoid general DNS backup.

Suggested commit message: `Fix Excel compatibility and cumulative assessment reporting`.

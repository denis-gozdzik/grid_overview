# Standardization-oriented reporting

The workbook is intentionally split into two layers. The first layer supports workshops and decisions; the second retains technical evidence. The report never treats a dominant value as an approved standard. A target exists only when a human decision is explicitly marked `APPROVED` in the decision input.

## Decision-support sheets

The first sheets are ordered for a Product Owner / engineering review:

1. **Overview** — one-screen environment, collection/coverage and standardization summary plus the highest-priority observed hotspots.
2. **Standardization** — one row per parameter **and object scope**, not one row per WAPI object. Grid, Member, Network and Range populations are never mixed in the same percentage. It aggregates confirmed effective values, collection coverage, source levels and local override density.
3. **Decisions** — the human decision view. Yellow cells correspond to fields persisted in YAML. Editing the generated workbook alone is not persistent; copy decisions to the decision file before regenerating.
4. **Exceptions** — actionable object-level rows. Before a target is approved an observed local/different value is `PENDING_DECISION`; after an approved target exists a mismatch can become `DEVIATION` or an explicitly selected `APPROVED_EXCEPTION`.
5. **Grid_Comparison** — important parameters side by side across Grids. With one Grid it explicitly reports that cross-Grid comparison is not applicable instead of emitting pseudo-differences.
6. **Coverage** — detailed collection/query/field evidence.
7. **Manual_Review** — organizational/process questions that WAPI cannot establish.

All existing technical sheets remain after this layer, including `DHCP_Effective`, `DHCP_Options`, `DHCP_Raw`, inventory sheets, templates, filters, reservations, source metadata and errors.

## Terminology

- **Observed value**: a confirmed normalized effective value from collected evidence.
- **Common observed value**: the unique most frequent confirmed value within one object scope. It is descriptive only.
- **Population objects**: the collected RAW object population for that scope (for example all Networks). This is the denominator for common-value, confirmed-value, inherited and local-override percentages.
- **Query coverage**: the share of the scope population for which the corresponding effective query returned object evidence.
- **Collection status**: whether the object population itself was collected completely. A query-level `PARTIAL` caused only by an unrelated missing field can still be complete for another parameter when every object was returned and no collection error exists.
- **Confirmed value**: a unique, complete normalized effective value for an object.
- **Explicit not configured**: parameter-specific WAPI evidence explicitly reporting `NOT_DEFINED` / `NOT_CONFIGURED`; absence of a row is never treated as not configured.
- **Unresolved**: a population object for which the parameter is neither confirmed nor explicitly not configured.
- **Consistency**: a descriptive classification such as `CONSISTENT`, `MULTIPLE_VALUES`, `LOCAL_OVERRIDES`, `DIFFERENT_SOURCE`, `ONLY_IN_SOME_GRIDS`, `NOT_CONFIGURED` or `INSUFFICIENT_DATA`.
- **Standardization candidate**: whether evidence is ready for human review. It is not an approval.
- **Approved target**: a target supplied by a human decision with `status: APPROVED`.
- **Local override**: a confirmed `configured_here=true` value below the Grid root. Grid-root configuration is central configuration, not counted as a local override.
- **Deviation**: a confirmed effective value that differs from an approved target. A difference cannot be a deviation before a target is approved.
- **Approved exception**: an approved-target mismatch explicitly matched by an `approved_exceptions` selector in decision YAML.

## Decision persistence

Generate a report once. It also writes:

```text
standardization_decisions.template.yaml
```

Copy that file to a private local path, for example:

```text
config/standardization_decisions.yaml
```

`config/*` is ignored by Git except the checked-in examples. Apply decisions during live or offline reporting:

```powershell
python -m infoblox_inventory \
  --offline output/run-001/raw \
  --decisions config/standardization_decisions.yaml \
  --output-dir output/assessment-with-decisions
```

or:

```powershell
python -m infoblox_inventory \
  --config config/grids.work.yaml \
  --grid LAB \
  --all \
  --decisions config/standardization_decisions.yaml \
  --output-dir output/lab-assessment
```

Example:

```yaml
version: 1

decisions:
  dhcp.lease_time.range:
    status: APPROVED
    proposed_target: 28800
    approved_target: 28800
    exceptions_allowed: true
    exception_rule: "Short-lived PXE ranges may use 3600 seconds"
    owner: "Infoblox Product Owner"
    decision_date: "2026-09-21"
    notes: "Approved during the standardization workshop"
    comparison_mode: exact
    approved_exceptions:
      - grid: GRID-A
        object_ref: range/example:10.0.0.10/10.0.0.20/default
```

Supported decision states are `PENDING`, `UNDER_REVIEW`, `APPROVED`, `REJECTED`, `DEFERRED` and `NOT_APPLICABLE`. Unknown decision IDs are rejected rather than silently ignored. Legacy unscoped IDs such as `dhcp.lease_time` are also rejected with a migration hint; a human must choose the intended scope rather than silently applying one target to several populations.

`comparison_mode: exact` is the default. `unordered_list` is available for values explicitly judged to be order-insensitive; it must be a conscious decision because some DHCP option order can be semantically relevant.

## Standardization matrix

The first increment covers normalized DHCP/PXE/DDNS parameters already present in the existing collector, including lease, DNS, domain, domain search, gateway, NTP, PXE options/scalars and currently normalized DDNS fields. Each supported parameter is expanded into explicit scope-specific decision IDs such as `dhcp.lease_time.grid`, `dhcp.lease_time.network` and `dhcp.lease_time.range`. Fixed-address rows cannot enter Network/Range statistics unless a future parameter explicitly declares that scope. It does **not** claim new DDNS collection coverage: rows with insufficient evidence are intentionally marked as blocked/insufficient.

For each scoped question the matrix exposes:

- population objects and effective-query object coverage;
- a separate collection status, so a complete object read is not confused with incomplete parameter evidence;
- the exact WAPI field required by the parameter and whether that field was explicitly unavailable;
- confirmed effective values, explicit `NOT_CONFIGURED` objects and unresolved objects as separate populations;
- confirmed/resolved/unresolved percentages against the full scoped object population;
- distinct observed values and frequency distribution;
- unique common observed value when one exists;
- common-value percentage against the full scope population;
- local override count and percentage against the full non-Grid scope population;
- inherited count/percentage and source-level distribution;
- evidence/coverage state derived from collector Coverage, collection errors and normalized evidence;

A collector-level `PARTIAL` caused only by an unrelated unreadable schema field does not automatically degrade every parameter on that object type. Conversely, a real pagination/transport failure or an unavailable field required by the parameter remains incomplete and is never upgraded from surviving normalized rows.
- descriptive consistency classification;
- decision overlay and evidence sheet.

This lets a workshop move from “what values exist?” to “which questions are already converged, which have multiple values, which are dominated by local configuration, and what needs a Product Owner decision?” without changing the underlying WAPI evidence.

## Exceptions workflow

Before approval, `Exceptions` contains only interesting confirmed rows (local overrides or rows differing from the common observed value) and labels them `PENDING_DECISION`. It intentionally does not call them non-compliant or deviations.

After an approved target exists:

- matching objects are summarized in the matrix and omitted from the actionable exception list;
- a confirmed mismatch is `DEVIATION`;
- an explicitly selected mismatch can be `APPROVED_EXCEPTION`;
- unresolved evidence becomes `INSUFFICIENT_DATA` for that approved target.

The sheet includes object/source refs so engineers can trace every item back to technical evidence. It remains read-only with respect to Infoblox; it is preparation for a future remediation backlog, not an execution plan.

## Multi-Grid behavior

`Grid_Comparison` puts the same **scoped** standardization question across all collected Grids. Each Grid cell shows its confirmed observed distribution with that Grid's object-population denominator. The matrix also shows global distinct values, the common observed value, override count and coverage. With only one Grid the sheet states that comparison requires at least two Grids.

The current comparison is parameter-centric; it does not claim that networks in unrelated site structures are equivalent objects.

## Report safety

The reporting increment makes no additional WAPI calls and adds no write method. Existing RAW/effective separation and Member inheritance limitations remain unchanged. A shadow/raw value is never promoted to an effective value just to make a standardization cell complete.

The Excel serializer keeps table-owned AutoFilters only. The Overview hotspot table is an ordinary OOXML table with no overlapping worksheet filter, and the existing OOXML validator continues to check table IDs/names, ranges, headers, column counts and relationships.

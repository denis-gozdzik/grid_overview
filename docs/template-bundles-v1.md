# Template Bundles v1

## Purpose

Template Bundles v1 turns separate stored NetworkTemplate and RangeTemplate records into a human-facing provisioning view.

The primary question is no longer:

```text
What fields exist on this template object?
```

but:

```text
What reusable provisioning unit does this NetworkTemplate create,
which RangeTemplate does it attach, and what requires review?
```

A bundle is descriptive stored configuration. It is not an approved standard and it does not prove that an existing Network was historically created from the template.

## Bundle relationship

For every collected NetworkTemplate, the bundle layer follows the stored `range_templates` relationship.

Statuses:

- `LINKED` — referenced RangeTemplate was collected and resolved;
- `NETWORK_ONLY` — NetworkTemplate has no linked RangeTemplate;
- `MISSING_RANGE_TEMPLATE` — a configured link points to a RangeTemplate that was not collected/found;
- `ORPHAN_RANGE_TEMPLATE` — collected RangeTemplate is not referenced by any collected NetworkTemplate.

Orphans and missing links remain visible instead of being silently dropped.

## Provisioning family

The bundle keeps the DHCP server family as structure, while individual names/IP addresses remain local references.

Network member structures are normalized as:

- `dhcpmember` -> `INFOBLOX_MEMBER`;
- `msdhcpserver` -> `MS_SERVER`.

A coherent pair is classified as:

- `MS_SERVER` when Network and Range both use Microsoft DHCP;
- `INFOBLOX` when an Infoblox Network member is paired with MEMBER/FAILOVER Range semantics;
- `MIXED_OR_INCONSISTENT` when the stored relationship does not align;
- `ORPHAN_*` for standalone Range templates.

This classification describes stored template construction only.

## Range geometry

When a linked NetworkTemplate has a valid IPv4 prefix, Range geometry is expressed relative to the future subnet instead of as an invented IP address.

Examples:

- start offset 1 -> `FIRST_USABLE`;
- start offset 4 -> `HOST_OFFSET_4`;
- end offset equal to subnet last usable -> `LAST_USABLE`;
- other end offsets retain their relative host offset and distance from broadcast.

Exclusions are shown with offset, count and distance from broadcast where the parent prefix is known.

V1 does not yet use geometry to approve or merge bundle families automatically. It exposes the comparable evidence needed for that later step.

## DHCP options review

WAPI exposes both:

- object-level `use_options`, the use flag for the `options` field;
- per-option `use_option`.

If one or more stored options have `use_option=true` while the owning template has `use_options=false`, the bundle is flagged:

```text
STORED_OPTIONS_DISABLED_BY_CONTAINER
```

The stored values remain evidence, but they are not promoted to active template behavior.

This distinction is important for legacy templates that may contain historical option values.

## Association review

A RangeTemplate with:

```text
server_association_type = NONE
```

while also retaining a member/MS/failover reference is flagged:

```text
ASSOCIATION_NONE_WITH_SERVER_REFERENCE
```

A mismatch between Network member family and linked Range association is additionally flagged:

```text
NETWORK_RANGE_ASSOCIATION_MISMATCH
```

These are review flags, not automatic defects or remediation instructions.

## Workbook UX

The intended default user path is:

```text
Overview
   ↓
Template_Bundles
   ↓
Template_Models
   ↓
Template_Grid_Matrix
   ↓
Template_Assignments
```

Detailed evidence remains in the same workbook but is hidden by default.

Visible decision/catalog sheets are intentionally limited so the workbook remains usable when nine Grids are combined.

`Template_Models` keeps deterministic canonical payload/digest columns in the workbook but hides those technical columns by default.

`Template_Grid_Matrix` suppresses absent `NOT_CONFIGURED=null` rows. Full absence/activity evidence remains in hidden `Template_Semantics`.

## Relationship to Template Semantic Model

Template Bundles do not replace semantic model IDs.

They combine:

- Network Template identity and Network semantic model;
- linked Range Template identity and Range semantic model;
- Network prefix;
- DHCP server family;
- Range geometry;
- fixed-address template links;
- option container state;
- review flags.

The next cross-Grid step can therefore search for common provisioning patterns without equating local IP addresses, DNS domains or member names.

## Next step

After validating bundles on real Grids:

```text
Template Bundles
      ↓
Bundle Shape / parameter candidates
      ↓
cross-Grid common provisioning models
      ↓
Observed Profile Shape ↔ Bundle Shape Alignment
      ↓
Candidate Review
```

Bundle family discovery should treat prefix/range geometry as candidate parameters where appropriate rather than assuming every literal offset/count is a global standard.

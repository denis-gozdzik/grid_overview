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

Bundle Model v1 additionally canonicalizes this geometry relative to the parent subnet:

- start uses `FIRST_USABLE` or `HOST_OFFSET_N`;
- end uses `LAST_USABLE` or a margin from broadcast;
- exclusions are anchored to the nearest stable edge (start or end) with length preserved.

This means, for example, a /24 and /27 template can share one Bundle Model when both start at host offset 4, end at last usable, and reserve the same three-address tail block relative to broadcast. Prefix length and absolute address count remain visible parameters instead of automatically creating separate provisioning families.

## DHCP options review

WAPI exposes both:

- object-level `use_options`, the use flag for the `options` field;
- per-option `use_option`.

If one or more stored options have `use_option=true` while the owning template has `use_options=false`, the bundle reports:

```text
Options State = DISABLED (use_options=False)
Stored Enabled Options = <observed option names>
```

This is evidence state, not automatically a review defect. The stored values remain visible but are not promoted to active template behavior.

Review attention is reserved for construction issues such as missing/orphan relationships or Network/Range association mismatches.

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

## Attention signal

Human-facing bundle rows expose a compact `Attention` value:

- `OK` — no construction inconsistency or unresolved relationship detected;
- `REVIEW` — relationship/association construction requires review, including missing linked RangeTemplate, orphan RangeTemplate or explicit Network/Range association mismatch.

Informational evidence such as a disabled option container stays in its dedicated state columns and does not inflate the review count.

## Workbook UX

The intended default user path is:

```text
Overview
   ↓
Data_Index
   ↓
Template_Bundle_Models
   ↓
Template_Bundles
   ↓
Template_Models / Template_Grid_Matrix
```

Detailed evidence remains in the same workbook but is hidden by default. `Data_Index` inventories every sheet, shows row counts/visibility/purpose, links to visible analysis sheets and identifies hidden technical evidence for drill-down.

Visible catalog sheets are intentionally limited so the workbook remains usable when nine Grids are combined. Governance/manual-review and decision-workflow sheets remain available through `Data_Index` but do not occupy the primary template-discovery navigation surface.

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

## Bundle Model identity

Each bundle row receives a deterministic:

```text
BNDL-SH1-<short sha256>
```

The canonical bundle shape includes provisioning family, Network/Range semantic model IDs, normalized relative Range geometry, fixed-address-template count and relationship status.

`Template_Bundle_Models` aggregates identical bundle shapes across templates and Grids and reports bundle count, Grid count/coverage, participating semantic models and template names.

For user-facing navigation it also exposes a deterministic human-readable `Model Signature`, for example:

```text
MS_SERVER | /24,/27 | +4→LAST_USABLE; excl3@tail-5
```

The signature is descriptive and intentionally compact. The canonical identity remains `BNDL-SH1-*`; the signature is not a semantic business name and need not be globally unique across future schema versions.

This is still descriptive evidence, not an approved organizational standard.

## Nine-Grid validation contract

Synthetic validation covers the intended multi-Grid behavior directly:

- nine Grids with different DNS servers, domain names, gateway literals, template names and Microsoft DHCP server references collapse to one Bundle Model when their semantic policy and normalized construction are equivalent;
- `/24` and `/27` can share the same model when the relative Range geometry is equivalent;
- one active policy difference such as lease time creates a separate model instead of being hidden as a local parameter;
- Grid coverage is calculated from distinct participating Grids, not raw object count.

This contract is designed to prevent a large Grid from dominating the cross-Grid interpretation and to keep local addressing/naming separate from reusable provisioning structure.
## Next step

After validating bundle models on real Grids:

```text
Template Bundle Models
      ↓
cross-Grid parameter/commonality analysis
      ↓
Observed Profile Shape ↔ Bundle Shape Alignment
      ↓
Candidate Review
```

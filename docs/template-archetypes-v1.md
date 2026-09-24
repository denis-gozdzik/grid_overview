# Template Archetypes v1

## Why this layer exists

Exact semantic/template bundle fingerprints are valuable evidence but are too precise to be the primary multi-Grid reporting model. Small policy or geometry differences can create many exact Bundle Model IDs and make the workbook look fragmented even when the same broad provisioning construction is reused.

Template Archetypes v1 introduces a hierarchy:

```text
Archetype
  ↓
Variant
  ↓
Instance
```

Review-only objects are kept outside this hierarchy.

## Archetype

An Archetype represents coarse provisioning construction.

Identity intentionally includes:

- relationship structure: Network + Range or Network only;
- provisioning family;
- Range association mode where applicable;
- whether Fixed Address templates are structurally linked.

Identity intentionally does not include:

- Grid name;
- template name;
- prefix length;
- DNS/domain/server literals;
- exact Range geometry;
- exact policy literals;
- exact semantic model IDs.

Examples:

```text
Microsoft DHCP — Network + Range
Infoblox DHCP — Network + Range (MEMBER)
Infoblox DHCP — Network + Range (FAILOVER)
Infoblox DHCP — Network Only
```

This is the primary human-facing grouping across Grids.

## Variant

A Variant is an exact Bundle Model within an Archetype.

Variants retain the existing deterministic `BNDL-SH1-*` evidence and therefore preserve differences such as:

- exact normalized Range geometry;
- exact active policy differences;
- exact semantic Network/Range model combinations.

One Archetype may therefore contain many Variants.

Example:

```text
Archetype:
Microsoft DHCP — Network + Range

Variant A:
start +4 → LAST_USABLE; tail exclusion

Variant B:
start +10 → BCAST-16; no exclusion
```

The variants are useful when the user wants to understand what differs inside a common provisioning family.

## Instance

An Instance is the concrete stored template relationship on one Grid:

- Grid;
- NetworkTemplate;
- RangeTemplate;
- prefix;
- Archetype;
- Variant;
- Range start/end/exclusions;
- option-container state.

This is the drill-down from a reusable model to real configured objects.

## Review

The following do not become Archetypes:

- orphan RangeTemplate;
- missing linked RangeTemplate;
- inconsistent Network/Range association;
- other explicit bundle review conditions.

They are shown only in `Template_Review`.

This prevents inventory hygiene issues from polluting the reusable template catalog.

## Commonality

Archetypes report descriptive scope:

- `ALL_COLLECTED_GRIDS`
- `MULTI_GRID`
- `GRID_SPECIFIC`

The number of collected Grids is dynamic. There is no architecture assumption that the environment contains 7, 8, 9 or any other fixed count.

Grid coverage is based on distinct participating Grids, not object count.

## Workbook UX

Primary visible sheets are:

```text
Overview
Template_Archetypes
Template_Grid_Map
Template_Variants
Template_Instances
Template_Review
Data_Index
```

Exact Bundle Models, semantic fingerprints, Grid Matrix, profile analysis, standardization workflow and raw evidence remain in the same workbook but are hidden by default.

Technical Archetype/Variant IDs are preserved but hidden in the human-facing worksheets.

## Intended questions

The primary workbook should now answer, in order:

1. What provisioning constructions exist?
2. On which Grids do they exist?
3. How many exact variants exist inside each construction?
4. Which concrete templates implement each variant?
5. Which objects do not belong in the reusable catalog and require review?

Only after those questions are answered should users drill into exact semantic evidence or policy details.

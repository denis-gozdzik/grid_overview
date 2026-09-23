# Template Semantic Model v1

## Purpose

Template Semantic Model v1 discovers reusable configuration **shapes** from stored Network/Range templates without requiring literal Grid-local values to be identical.

The goal is to answer questions such as:

- which existing templates are structurally the same even when DNS, domain, member or PXE endpoints differ by Grid;
- which differences are policy/structure differences and therefore should create a different model;
- which values are stored but inactive and therefore must not be treated as active configuration;
- which local values must remain available for later per-Grid parameterization.

This layer is descriptive. A discovered model is not an approved standard and semantic similarity does not prove that an observed Network/Range was created from a template.

## Evidence boundary

Inputs are typed `RAW_CONFIGURATION` records from:

- `networktemplate`
- `rangetemplate`

Fixed Address templates remain outside this v1 model and will be handled with Reservation Profile work.

No effective inheritance claim is introduced for templates.

## Parameterization roles

V1 uses explicit roles instead of inferring `CONSTANT` or `GRID_PARAMETER` from a single Grid.

### POLICY_LITERAL

The active literal value is part of model identity.

Examples:

- DHCP lease time;
- DDNS enabled and behavior flags;
- DDNS TTL;
- BOOTP behavior;
- PXE lease policy;
- authority;
- lease recycling/scavenge settings.

A different active value creates a different shape.

### GRID_LOCAL

The literal value is retained in evidence and the Grid matrix but replaced in shape identity by a placeholder containing type/cardinality.

Examples:

- DNS servers;
- domain name;
- domain search;
- NTP servers;
- DDNS domain;
- next server;
- boot server;
- boot file;
- option 66;
- option 67.

Two Grids can therefore use different addresses/domains while still sharing one reusable template model.

### TOPOLOGY_DERIVED

The literal value is topology-specific and does not enter shape identity directly.

V1 uses this role for DHCP router/gateway option 3. Because a Network Template has no concrete instantiated subnet, an exact `HOST_OFFSET_N` cannot be derived from a literal router address at template-definition time. The shape therefore preserves activity, type and cardinality while retaining the stored value separately.

### STRUCTURE_LITERAL

Template structure is part of identity.

Examples:

- Network template netmask / allow-any-netmask;
- Range offset / number of addresses;
- Range association family;
- Range exclusions.

### REFERENCE_LOCAL

Names/addresses of referenced infrastructure are local parameters. Shape identity retains activity, object/list form and cardinality, while literal references remain in the Grid matrix.

Examples:

- DHCP members;
- delegated member;
- linked Range/Fixed Address templates;
- Range member/MS server/failover references.

## Activity states

Every known semantic parameter is represented explicitly as:

```text
ACTIVE_VALUE
INACTIVE
NOT_CONFIGURED
UNRESOLVED
```

For scalar fields with `use_*` flags:

- `use_*=true` + stored value -> `ACTIVE_VALUE`;
- `use_*=false` -> `INACTIVE`;
- required activation evidence present but incomplete -> `UNRESOLVED`;
- field and activation evidence absent -> `NOT_CONFIGURED`.

For DHCP options both `use_options` and per-option `use_option` are considered.

A stored literal under an inactive option remains visible as evidence but does not enter shape identity.

Example:

```text
Grid A: lease=43200, use_option=true, use_options=false
Grid B: lease=86400, use_option=true, use_options=false

Both semantic states:
INACTIVE

Result:
same template shape
```

This prevents historical/stored values from creating false model differences.

## Standard DHCP options

Known DHCP option semantics are mapped only in the standard DHCP vendor class:

- 3 router/gateway
- 6 DNS servers
- 15 domain name
- 42 NTP servers
- 51 lease time
- 66 TFTP server name
- 67 bootfile name
- 119 domain search

A colliding code in another vendor/option space remains a separate generic option and is conservatively treated as `POLICY_LITERAL`.

Unknown active options are never silently dropped from model identity.

## Stable model identity

A model ID is a deterministic SHA-256-derived identifier over a canonical shape payload.

Network Template:

```text
NTPL-SH1-<short sha256>
```

Range Template:

```text
RTPL-SH1-<short sha256>
```

The payload includes for every semantic parameter:

- dimension;
- parameterization role;
- activity state;
- literal value for policy/structure fields, or placeholder kind/cardinality for local/topology/reference fields.

Template name, Grid name, comment, object reference and Grid-local literal values do not enter shape identity.

## Workbook views

### Template_Models

One row per distinct reusable shape:

- model ID;
- template type;
- template count;
- Grid count and Grid coverage;
- Grid list;
- observed template names;
- dimensions;
- shape parameter count;
- canonical shape and full SHA-256.

This is the primary cross-Grid template catalog.

### Template_Grid_Matrix

One row per local/topology/reference parameter inside a model.

Columns include every collected Grid. Cells preserve the actual stored values per template/Grid.

This view separates:

```text
common model
+
Grid-specific parameters
```

### Template_Assignments

One row per Network/Range template:

- Grid;
- template name/ref;
- assigned model ID;
- active/inactive/not-configured/unresolved counts;
- local parameter count;
- dimensions.

### Template_Semantics

Long-form parameter evidence used to explain model identity.

This sheet is generated but hidden by default because it is technical drill-down, not the primary user interface.

## What v1 deliberately does not infer

V1 does not label an observed field as globally:

- CONSTANT;
- GRID_PARAMETER;
- SITE_PARAMETER;
- approved standard.

Those conclusions require multiple Grids/templates and later review.

Instead v1 uses deterministic parameterization roles chosen from the parameter's semantics. When all nine Grids are available, later cross-Grid analysis can measure whether a `GRID_LOCAL` candidate actually varies per Grid and whether a `POLICY_LITERAL` is globally consistent.

## Next steps

After validation on real template evidence:

```text
Template Semantic Model
        ↓
Template Bundles
        ↓
Observed Profile Shape ↔ Template Shape Alignment
        ↓
Multi-Grid template catalog / parameter matrix
        ↓
Candidate Review
        ↓
PO decisions
```

The long-term report should keep model/catalog/matrix views user-facing and move detailed evidence behind drill-down or hidden technical sheets.

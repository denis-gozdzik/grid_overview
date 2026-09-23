# Profile Dimensions v1

## Purpose

Profile Dimensions v1 decomposes the existing exact Network/Range profile model into independent deterministic configuration dimensions.

The existing core fingerprints remain unchanged for backward compatibility:

```text
NET-FP1-...
RNG-FP1-...
```

Dimensions add a second descriptive view. They do not replace the existing core profile, approve a standard, infer compliance, or prescribe remediation.

## Dimensions

### DHCP Core

Identity inputs:

- DHCP lease time
- DNS servers
- domain name
- derived gateway convention

IDs:

```text
NET-CORE1-...
RNG-CORE1-...
```

This dimension uses the same functional evidence semantics as the existing core fingerprint.

### DNS/DDNS

Identity inputs are the scope-supported subset of:

- domain search
- DDNS enabled
- DDNS domain
- DDNS generate hostname
- DDNS TTL
- DDNS update fixed addresses
- DDNS use option 81
- DDNS update on lease renewal

Network-only parameters are not invented for Range.

IDs:

```text
NET-DNS1-...
RNG-DNS1-...
```

### PXE

Identity inputs are:

- next server
- boot server
- bootfile
- option 66 / TFTP server name
- option 67 / bootfile name
- PXE lease time

`pxe.lease_enabled` remains `COMPOSITE_LATER`. Its semantics are not yet sufficiently defined to enter a deterministic identity hash. It is exposed as a Deferred Input on PXE fingerprint and assignment rows.

IDs:

```text
NET-PXE1-...
RNG-PXE1-...
```

### Service

Identity inputs:

- NTP servers
- BOOTP deny

IDs:

```text
NET-SVC1-...
RNG-SVC1-...
```

### Range Association

The Association dimension uses the normalized RAW `server_association_type` family:

- `MS_SERVER`
- `MEMBER`
- `FAILOVER`
- `NONE`

Unexpected non-empty values remain unresolved rather than being coerced to a known family.

IDs:

```text
RNG-ASSOC1-...
```

`NONE` is a valid Association fingerprint even though that Range remains outside the DHCP-associated population for the other functional dimensions.

## Applicability inside dimensions

Different parameters can have different evidence-backed populations.

For example, a Range DHCP option can be applicable to `MS_SERVER`, while a Range scalar DDNS parameter can be outside that parameter's authoritative population.

Profile Dimensions v1 does not force those inputs into a false common denominator.

For an object that belongs to the dimension's base population, each identity input is represented as one of:

```text
VALUE
NOT_CONFIGURED
NOT_APPLICABLE
UNRESOLVED
```

`NOT_APPLICABLE` is an explicit semantic state and can enter a dimension payload.

`UNRESOLVED` blocks the dimension fingerprint for that object.

This keeps evidence applicability separate from configuration absence.

## Populations

Network functional dimensions use:

```text
DHCP_PROFILE_NETWORK_CANDIDATES
```

The broader `DHCP_RELEVANT_NETWORK_CANDIDATES` population remains available for topology/context reporting and can be larger than the functional profile denominator.

Range functional dimensions use:

```text
DHCP_ASSOCIATED_RANGES
```

Range Association uses:

```text
ALL_RANGES
```

Non-candidate Networks and non-associated Ranges remain visible in assignment/composition output with explicit status instead of being silently dropped.

## Determinism

A dimension ID is a SHA-256-derived identifier over a canonical payload containing:

- schema version
- profile type
- dimension key
- ordered semantic field mapping

IDs do not depend on prevalence, input order, workbook order or display rank.

The full SHA-256 digest and canonical payload are retained.

## Workbook views

### Profile_Dimensions

One row per distinct resolved dimension fingerprint with:

- scope and dimension
- population basis
- deterministic ID
- prevalence
- identity inputs
- deferred inputs
- bounded display values
- canonical payload
- full SHA-256

### Profile_Dimension_Assignments

One row per object/dimension combination.

Statuses include:

- `PROFILED`
- `UNRESOLVED_DIMENSION_INPUTS`
- `NOT_APPLICABLE_TO_DHCP_PROFILE`
- `UNRESOLVED_ASSOCIATION`

Missing and deferred inputs remain explicit.

### Profile_Dimension_KPIs

Per profile/dimension:

- applicable objects
- profiled objects and %
- unresolved objects and %
- distinct fingerprints
- top-1 prevalence
- singleton count

No weighted quality score is introduced.

### Profile_Compositions

One row per Network or Range combines its dimension outcomes:

```text
DHCP Core
DNS/DDNS
PXE
Service
Association
```

A cell contains the deterministic dimension fingerprint when resolved, otherwise its explicit status.

This view is designed as the later comparison surface for Template Dimensions and Observed ↔ Template Alignment.

## Relationship to existing Profile_Fingerprints

The existing `NET-FP1` / `RNG-FP1` functional core remains stable.

A DDNS-only or PXE-only difference therefore does not change the legacy core fingerprint. It changes only the corresponding dimension fingerprint.

This makes it possible to distinguish:

```text
same DHCP behavior
different DDNS behavior
```

without exploding one monolithic profile namespace.

## Next layer

The intended next increment is Template Dimensions v1.

It will project stored `networktemplate` / `rangetemplate` evidence into the same dimension semantics while preserving the distinction:

```text
observed object = effective/current-state evidence
template = stored RAW_CONFIGURATION blueprint
```

Only after both sides share the same semantic dimensions should Observed ↔ Template Alignment be calculated.

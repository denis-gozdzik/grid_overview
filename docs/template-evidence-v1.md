# Template Evidence v1

## Purpose

Template Evidence v1 extends the existing read-only inventory of reusable DHCP configuration so later profile/template comparison can use the same functional parameter families already assessed for Network and Range objects.

This increment does **not** decide which template is correct, does not infer a standard, and does not claim historical object origin from semantic similarity.

## Data representation

`networktemplate`, `rangetemplate` and `fixedaddresstemplate` remain:

```text
RAW_CONFIGURATION
```

Template rows represent stored configuration and observed use flags. They are not inheritance-resolved effective values.

DHCP options remain exposed separately through `Template_Options` with stored option values and `use_option` / `use_options` evidence.

## Added comparable DDNS evidence

The runtime WAPI schema determines which fields and `overridden_by` use flags are readable.

### Network Template

Template Evidence v1 requests the existing Network-profile DDNS scalars when readable:

- `enable_ddns`
- `ddns_domainname`
- `ddns_generate_hostname`
- `ddns_ttl`
- `ddns_update_fixed_addresses`
- `ddns_use_option81`
- `update_dns_on_lease_renewal`

Their schema-defined `use_*` flags are collected automatically from `overridden_by` metadata.

### Range Template

The Range-template projection requests the Range-profile DDNS scalars that exist in the current model:

- `enable_ddns`
- `ddns_domainname`
- `ddns_generate_hostname`
- `update_dns_on_lease_renewal`

Network-only DDNS TTL, fixed-address-update and option-81 fields are not invented for Range templates.

### Fixed Address Template

The reusable fixed-address projection additionally preserves:

- `enable_ddns`
- `ddns_domainname`
- `ddns_hostname`

This evidence is retained for a future Reservation Profile and is not folded into Network/Range profile identity.

## DHCP option evidence

Profile-relevant DHCP values such as lease time, DNS servers, domain name, domain search, router, NTP, option 66 and option 67 continue to come from the stored template `options` array.

Template Evidence v1 therefore does not duplicate DHCP option semantics as separate scalar fields.

## Template bundles

A Network Template already exposes readable relationships such as:

- `range_templates`
- `fixed_address_templates`

These relationships are preserved as stored configuration and can later support deterministic template-bundle analysis.

Template Evidence v1 does not yet produce bundle fingerprints or object/template alignment.

## Object origin / provenance

The saved LAB WAPI 2.13.7 schemas show `template` on both `network` and `range` with write-only support:

```text
supports: w
```

That means a template may be supplied when creating an object, while a later GET cannot reconstruct that origin from this field in the observed LAB schema.

The collector therefore treats Network/Range `template` as **optional provenance evidence**:

- if runtime WAPI exposes it as readable, it is collected and preserved;
- if it is absent or unreadable, Coverage records `NOT_EXPOSED_BY_WAPI`;
- absence of optional origin evidence does **not** downgrade unrelated DHCP collection to `PARTIAL`.

Future semantic matching between observed configuration and a stored template must therefore be labeled as alignment/match evidence, not historical `CREATED_FROM_TEMPLATE` proof unless readable provenance explicitly supports that claim.

## Next layer

After Template Evidence v1 is validated, the intended sequence is:

```text
Template Evidence
      ↓
Profile Dimensions / Template Dimensions
      ↓
Template Bundles
      ↓
Observed ↔ Template Alignment
      ↓
Candidate Review
      ↓
PO decisions
      ↓
Compliance / migration delta
```

No collector in this increment performs writes and no new effective-inheritance claim is introduced for templates.

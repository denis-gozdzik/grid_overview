# Profile fingerprint v1 design

This document defines the deterministic profile-discovery v1 layer implemented in `src/infoblox_inventory/profile_discovery.py`. It is based on the existing Profile Input Readiness model and validation against the saved `lan-full5` LAB RAW archive. The observed counts below are validation evidence only; they are not constants, standards, or compliance thresholds.

## Purpose

Profile discovery answers:

- which recurring functional DHCP configuration models exist;
- how much of the applicable population each model represents;
- which objects cannot be profiled because required evidence is unresolved;
- which contextual signals correlate with each recurring model.

It does **not** approve a standard. The most common profile remains an observed current-state pattern until a human Product Owner explicitly approves a target.

## Separation of concerns

Keep three independent layers:

1. **Functional core profile** — effective DHCP behavior used to group objects.
2. **Feature overlay** — DDNS, BOOTP, PXE and other secondary settings shown alongside a core profile without automatically splitting the core profile.
3. **Source / inheritance profile** — provenance such as Grid, Member, Network, Range, configured-here and inherited observations. This must not change the functional profile when effective values are equal.

Context such as Network View, association type, comments, EA values and naming evidence is used for correlation and explanation. Context must not silently become a functional fingerprint input.

## Input usefulness evidence

Readiness and usefulness are different.

For every candidate input, future reporting should expose deterministic descriptive metrics:

- applicable population;
- resolved objects and resolved %;
- unresolved objects and unresolved %;
- distinct resolved states;
- distinct configured-value states;
- explicit NOT_CONFIGURED count;
- dominant state count;
- dominant state % of the applicable population;
- dominant state % of resolved objects;
- invariant-among-resolved flag;
- semantic role.

No weighted quality score is required.

An input may be READY and still be invariant or non-discriminative.

## Network Profile v1

Population:

```text
DHCP_RELEVANT_NETWORK_CANDIDATES
```

### Core fingerprint fields

Use these four fields:

1. effective DHCP lease time;
2. effective DNS servers;
3. effective domain name;
4. derived gateway convention.

DNS ordering must be preserved unless separate evidence proves that order is semantically irrelevant. Do not sort list-like DHCP values merely to reduce profile cardinality.

### Gateway convention

Do not fingerprint the literal router IP address.

Derive one of:

- `NOT_CONFIGURED`;
- `FIRST_USABLE`;
- `LAST_USABLE`;
- `HOST_OFFSET_<N>` for an in-subnet single router that is neither first nor last usable;
- `MULTIPLE_ROUTERS`;
- `OUTSIDE_SUBNET`;
- `EMPTY_VALUE`;
- `INVALID_VALUE`;
- `NO_PARENT_NETWORK`;
- `UNRESOLVED`.

The `HOST_OFFSET_<N>` form is necessary because the LAB evidence contains a strong repeated gateway-at-network-plus-3 convention that would be lost if every non-first/non-last router were reduced to `OTHER_IN_SUBNET`.

`EMPTY_VALUE` is not silently converted to NOT_CONFIGURED.

### Feature overlay, not core fingerprint v1

Keep these visible but do not let them split the Network core fingerprint in v1:

- domain search;
- NTP;
- BOOTP deny;
- DDNS enabled/domain/generate-hostname/TTL/update-fixed-addresses/option81/update-on-renewal;
- PXE nextserver/bootserver/bootfile;
- option 66;
- option 67;
- PXE lease time;
- PXE lease enabled.

Reason: in `lan-full5`, these fields are invariant among resolved objects, nearly invariant, deferred, or fully aligned with differences already expressed by the four core fields. Adding the variable DDNS/BOOTP bundle did not increase the number of exact core profiles in the LAB.

This is an observed v1 design choice, not a claim that these settings are unimportant.

## Range Profile v1

### Population and family

Only DHCP-associated ranges enter the functional Range profile:

```text
MEMBER + FAILOVER + MS_SERVER
```

`NONE` remains visible as a separate descriptive population and is not forced into a DHCP profile.

Range profiles are first separated by association family:

- `MS_SERVER`;
- `MEMBER`;
- `FAILOVER`.

Unexpected/unknown association values remain unresolved/manual-review context.

### Core fingerprint fields

Within the association family, use:

1. effective DHCP lease time;
2. effective DNS servers;
3. effective domain name;
4. derived gateway convention using the same rules as Network.

The stable Range fingerprint canonical form must include the association family plus these four core fields.

### Feature overlay, not core fingerprint v1

Keep the remaining Range candidate fields as overlays. In the LAB:

- DDNS enabled is completely correlated with association family;
- other Infoblox scalar DDNS/BOOTP inputs are invariant within the small Infoblox-managed population;
- domain search, NTP, option 66, option 67 and PXE lease time are invariant NOT_CONFIGURED across the associated population;
- nextserver, bootserver and bootfile remain unresolved for the two MEMBER ranges and must not enter a resolved fingerprint.

## Object profiling rules

A normal resolved fingerprint requires every required core field to be resolved.

- explicit `NOT_CONFIGURED` is a valid fingerprint state;
- `UNRESOLVED` is not a normal fingerprint value;
- an object missing any required core input is placed in an `UNRESOLVED_PROFILE_INPUTS` bucket with the missing parameter IDs;
- Range `NONE` is `NOT_APPLICABLE_TO_DHCP_PROFILE`, not unresolved and not a deviation.

Do not build partial normal profiles by silently dropping unresolved fields.

## Stable identity

Profile identity must not depend on prevalence rank.

Canonical payload example:

```json
{
  "schema_version": 1,
  "profile_type": "network",
  "fields": {
    "lease_time": {"status": "VALUE", "value": "..."},
    "dns_servers": {"status": "VALUE", "value": "..."},
    "domain_name": {"status": "VALUE", "value": "..."},
    "gateway_convention": {"status": "VALUE", "value": "HOST_OFFSET_3"}
  }
}
```

Range payload additionally contains `association_family`.

Serialize deterministically with sorted JSON keys and hash the canonical bytes. A display rank such as `Network Profile 1` may change with prevalence; the stable fingerprint ID must not.

Suggested IDs:

```text
NET-FP1-<short sha256>
RNG-FP1-<short sha256>
```

The short hash is a display identifier; retain the full digest internally if collision checks are implemented.

## Profile reporting

For every discovered profile show:

- stable fingerprint ID;
- display rank;
- object count;
- share of profiled population;
- share of applicable population;
- fingerprint field states;
- top contextual distributions;
- feature-overlay distributions;
- unresolved-object count outside normal profiles.

Also report:

- distinct profiles;
- Top-1 share;
- Top-3 share;
- number of profiles required to cover 80%, 90% and 95%;
- singleton profiles;
- unresolved-profile objects and %.

These are descriptive current-state metrics, not scores or compliance labels.

## LAB validation evidence

Saved `lan-full5` RAW contains:

```text
598 Networks
62 DHCP-relevant Network candidates
52 Ranges
49 DHCP-associated Ranges
47 MS_SERVER
2 MEMBER
3 NONE
```

### Network core

Of the 62 DHCP-relevant Networks, 55 have all four proposed core inputs resolved.

Exact core fingerprinting produces:

```text
55 profiled objects
8 distinct core profiles
largest profile: 44 / 55 = 80.0% of profiled objects
largest profile: 44 / 62 = 71.0% of the candidate population
4 singleton profiles
```

The dominant profile contains 44 objects, all in the default Network View and all with the same observed DHCP-relevance signature: members + Range parent + active DHCP option.

The current option-evidence limitation leaves 7 Network candidates outside normal profiles because their effective `options` response is an empty list. They remain unresolved by design.

### Gateway evidence

Network gateway convention after derivation:

```text
44 HOST_OFFSET_3
3 FIRST_USABLE
3 LAST_USABLE
4 NOT_CONFIGURED
1 EMPTY_VALUE
7 UNRESOLVED
```

Range gateway convention:

```text
45 HOST_OFFSET_3
2 FIRST_USABLE
1 LAST_USABLE
1 NOT_CONFIGURED
```

This is why a generic `OTHER_IN_SUBNET` category is insufficient.

### Range core

All 49 DHCP-associated Ranges have the four proposed core fields resolved.

Exact core fingerprinting with association family produces:

```text
49 profiled objects
5 distinct core profiles
largest profile: 45 / 49 = 91.8%
4 singleton profiles
```

The dominant Range profile contains 45 MS_SERVER ranges.

### Parent Network + Range pair

For DHCP-associated Ranges whose parent Network can also be resolved:

```text
44 / 49 associated Ranges
```

share the same dominant Network core profile and the same dominant Range core profile, with MS_SERVER association.

This is strong evidence of one recurring de-facto configuration model. It is not an approved standard.

## Out of scope for fingerprint v1

Do not add yet:

- automatic semantic names such as Corporate, Branch or Guest;
- approved-standard selection;
- compliance/deviation labels;
- clustering or fuzzy matching;
- weighted usefulness scores;
- inheritance/source metadata inside the functional fingerprint;
- EA/naming fields inside the functional fingerprint;
- remediation generation;
- attempts to resolve the two MEMBER Range PXE scalar wrappers without authoritative WAPI evidence.

The implementation produces four workbook views:

- `Profile_Usefulness`: deterministic evidence variability metrics without a weighted score;
- `Profile_Fingerprints`: exact recurring core-profile definitions, stable IDs, prevalence and bounded feature-overlay distributions;
- `Profile_Assignments`: object-to-profile mapping plus unresolved/not-applicable states;
- `Profile_KPIs`: coverage, distinct-profile count, top-1/top-3 share, 80/90/95% coverage counts and singleton count.

The implementation remains descriptive. It does not create approved standards, compliance states or remediation.

# Profile discovery v1: input readiness

The project aims to discover recurring current-state configuration models, such as Network and Range configuration profiles. A Product Owner may later review those models and approve standards. A common observed value does not establish an approved standard.

This increment implements **Profile Input Readiness** only. It answers whether an existing parameter has sufficiently reliable evidence for future automatic profile discovery. `READY` describes usable evidence; it does not mean correct, compliant or approved configuration.

The existing read-only pipeline remains:

```text
LIVE WAPI GET -> immutable RAW JSON -> normalization -> parameter analytics -> reporting
```

Readiness consumes existing scope-specific Standardization rows. It adds no collectors, WAPI endpoints or appliance requests and works with existing offline archives. It does not infer Member effective configuration or combine Grid, Member, Network and Range populations. Fixed Address evidence cannot enter Network or Range inputs.

## Input model

`src/infoblox_inventory/profile_readiness.py` defines an explicit input specification containing the profile, input key, label, source parameter ID, scope and semantic role. Every source ID must exist in `standardization.PARAMETER_SPECS` with the matching scope. An unknown ID is a development error; it must not disappear silently or create a new Standardization parameter.

The specification contains **21 Network Profile v1 inputs** and **18 Range Profile v1 inputs**. All listed IDs exist in the current parameter specification. `gateway_convention` uses the scope's router parameter with role `DERIVED_LATER`; readiness assesses literal router evidence only and does not yet convert it to `FIRST_USABLE`, `LAST_USABLE`, `OTHER_IN_SUBNET` or `OUTSIDE_SUBNET`.

`pxe.lease_enabled` is now `COMPOSITE_LATER`, not a direct input. The collected `enable_pxe_lease_time` field is not treated as a complete standalone semantic model. Populated scopes therefore report this input as `DEFERRED`, and deferred inputs are excluded from the Ready Input % denominator until the composite PXE lease semantics are defined.

## Profile population

Network readiness no longer assumes that every IPAM `network` object participates in DHCP. Two populations are retained deliberately:

```text
DHCP_RELEVANT_NETWORK_CANDIDATES
DHCP_PROFILE_NETWORK_CANDIDATES
```

`DHCP_RELEVANT_NETWORK_CANDIDATES` is broad topology/context evidence. It can include a parent-only Network, an externally managed Microsoft DHCP parent, or a Network with a generic active `use_*` flag.

`DHCP_PROFILE_NETWORK_CANDIDATES` is the narrower denominator used by Network fingerprint/readiness/dimension discovery. A Network enters this functional population only when at least one direct Infoblox DHCP signal exists:

- an Infoblox `dhcpmember` association;
- it is the parent of a MEMBER/FAILOVER Range;
- a profile-relevant scalar `use_*` flag is explicitly true;
- at least one stored DHCP option has `use_option=true`.

A parent of a `NONE` or `MS_SERVER` Range does not qualify by parenthood alone. A container-level `use_options=true` does not qualify by itself when no option has `use_option=true`.

This separation keeps topology relevance visible without turning context-only Networks into artificial unresolved profiles. `Profile_Readiness` retains both `Source Population Objects` (all Networks in scoped Standardization) and the profile-specific `Population Objects` denominator.

Range Profile v1 is segmented by RAW `server_association_type` before parameter readiness is calculated. The descriptive segments are `MS_SERVER`, `MEMBER`, `FAILOVER`, `NONE`, `OTHER` and `UNKNOWN`. Null/empty association evidence is `NONE`; unexpected non-empty values remain `OTHER`/ `UNKNOWN` and are preserved in `Profile_Populations` rather than coerced into a known class.

Range parameter families use different evidence-backed denominators:

- option-based effective DHCP inputs use `DHCP_ASSOCIATED_RANGES` = MEMBER + FAILOVER + MS_SERVER;
- Infoblox scalar inputs use `INFOBLOX_MANAGED_RANGES` = MEMBER + FAILOVER;
- an MS_SERVER Range is added to a scalar parameter's applicable population only when that scalar has authoritative COMPLETE or explicit NOT_CONFIGURED evidence from WAPI;
- `NONE` is retained as a visible segment and is not silently treated as an evidence failure or deviation.

`MS_SERVER` means externally managed for the purpose of applicability; it does **not** mean `NOT_CONFIGURED`.

If Networks exist but no functional DHCP profile candidate can be established from the available evidence, readiness is `NOT_READY`, not `NOT_APPLICABLE`.

## Functional value proof vs source proof

Profile readiness now separates the effective functional value from inheritance/source provenance. For one object and parameter, multiple COMPLETE non-multisource rows count as one confirmed functional value when every row resolves to the same `effective_value`, even if `source_level`, `source_ref`, `configured_here` or `inherited` differ.

Example:

```text
Grid    -> 7200
Network -> 7200
```

For a future functional profile this is one confirmed value: `7200`. The different source observations remain intact in normalized technical evidence for a future inheritance/source profile.

Two or more distinct effective values remain unresolved/conflicting. Any `multisource=True` observation remains conservative and is not promoted to a confirmed functional value. This new proof is local to Profile Readiness/Profile Discovery; Standardization keeps its existing source-sensitive semantics.

## Evidence and classification

The primary metric is **Resolved Evidence %**, with the scope's **Population Objects** as its denominator:

```text
Resolved Evidence % =
    (Confirmed Objects + Explicit Not Configured) / Population Objects * 100
```

Only explicit parameter evidence counts as `NOT_CONFIGURED`. A missing normalized scalar row remains unresolved. For the bounded assessed DHCP option set, one additional authoritative case is allowed **inside Profile Input Readiness only**: when a Network/Range `_inheritance=True` response contains a fully recognized effective `options` group structure, an assessed option absent from every returned group counts as explicit `NOT_CONFIGURED` for readiness accounting. The normalized `DHCP_Options` evidence remains unchanged and contains no synthetic absence rows. Malformed, plain/unwrapped, or empty option responses never trigger this inference.

Confirmed Value % alone is insufficient because an explicit not-configured state is also usable evidence.

Classification follows this order:

1. Population zero is `NOT_APPLICABLE` only when collection status `COMPLETE` or `EMPTY` confirms that the scope is truly empty.
2. Population zero combined with `PARTIAL`, `ERROR` or `UNKNOWN` collection is `NOT_READY`: the population could not be established.
3. A hard blocker makes any populated input `NOT_READY`, regardless of its percentage.
4. Otherwise apply the thresholds below using exact evidence counts, not the rounded display percentage.

| Readiness | Resolved Evidence % |
| --- | --- |
| `READY` | At least 95.0% |
| `CONDITIONAL` | At least 80.0% and below 95.0% |
| `NOT_READY` | Below 80.0% |

Hard blockers are:

- Collection Status: `ERROR`, `PARTIAL` or `UNKNOWN`.
- Required Field Status: `NOT_EXPOSED_BY_WAPI`.
- Evidence Status: `ERROR`, `NOT_EXPOSED_BY_WAPI` or `INSUFFICIENT_DATA`.

`DEFERRED` is not an evidence failure. It marks an input whose semantics intentionally require a later composite derivation and excludes that input from the readiness-rate denominator.

A missing source Standardization row cannot prove zero population. It stays `NOT_READY` with a missing-evidence reason; it must not be converted to `NOT_APPLICABLE` or explicit `NOT_CONFIGURED`. Missing or invalid population/resolved metrics and unrecognized statuses are also handled conservatively as `NOT_READY`.

A failed or incomplete collection with zero captured objects does not establish an empty scope. Only authoritative `COMPLETE`/`EMPTY` collection evidence can produce `NOT_APPLICABLE` for a zero population.

Every result preserves the evidence counts and denominators and includes a concise Readiness Reason. A successful object query can coexist with unresolved parameter evidence. Conversely, normalized rows do not override a collection failure.

| Population | Confirmed | Explicit not configured | Unresolved | Resolved evidence | Result with no blockers |
| --- | --- | --- | --- | --- | --- |
| 130 | 127 | 3 | 0 | 100.0% | `READY` |
| 130 | 127 | 0 | 3 | 97.7% | `READY` |
| 130 | 117 | 0 | 13 | 90.0% | `CONDITIONAL` |
| 1000 | 799 | 0 | 201 | 79.9% | `NOT_READY` |

The Standardization layer still exposes percentages rounded to one decimal place for reporting. Readiness classification does **not** use that rounded value at the 80%/95% thresholds. It recomputes the exact ratio from integer evidence counts:

```text
exact resolved ratio =
    (Confirmed Objects + Explicit Not Configured) / Population Objects
```

This prevents, for example, an exact 94.95% result from rounding to a displayed 95.0% and being promoted to `READY`. The Readiness Reason includes the exact ratio and object counts so a rounded display value cannot hide the boundary decision.

### Existing evidence semantics retained

`Evidence Status = PARTIAL` alone is not a hard blocker. For example, complete collection with 97.7% resolved parameter evidence can be `READY`. This differs from `Collection Status = PARTIAL`, which always blocks populated inputs.

`Required Field Status = NOT_EXPOSED_IN_SOME_GRIDS` is also distinct from `NOT_EXPOSED_BY_WAPI`. The former does not introduce an additional blocker beyond the rules above, and the reason flags this partial field availability. The resolved percentage and all original status columns remain visible for review.

Readiness consumes the final parameter-aware Collection Status. Existing Standardization semantics may treat a collector-level partial status caused solely by an unrelated missing field as complete for another parameter when all object evidence was returned and no collection error was recorded. Recorded query failures remain blocking. This increment does not alter that distinction.

## Network Profile v1 candidates

Each row is a Network-scoped input. The gateway row has semantic role `DERIVED_LATER`; `pxe.lease_enabled` is `COMPOSITE_LATER`; the remaining inputs are `DIRECT`.

| Input | Source parameter ID |
| --- | --- |
| DHCP lease time | `dhcp.lease_time.network` |
| DNS servers | `dhcp.dns_servers.network` |
| Domain name | `dhcp.domain_name.network` |
| Domain search | `dhcp.domain_search.network` |
| Gateway convention (router evidence) | `dhcp.router.network` |
| NTP servers | `dhcp.ntp_servers.network` |
| BOOTP denied | `dhcp.deny_bootp.network` |
| DDNS enabled | `ddns.enabled.network` |
| DDNS domain | `ddns.domain.network` |
| DDNS generate hostname | `ddns.generate_hostname.network` |
| DDNS TTL | `ddns.ttl.network` |
| DDNS update fixed addresses | `ddns.update_fixed_addresses.network` |
| DDNS use option 81 | `ddns.use_option81.network` |
| DDNS update on lease renewal | `ddns.update_on_renewal.network` |
| PXE next server | `pxe.nextserver.network` |
| PXE boot server | `pxe.bootserver.network` |
| PXE bootfile | `pxe.bootfile.network` |
| PXE TFTP server name | `pxe.tftp_server_name.network` |
| PXE bootfile name option | `pxe.bootfile_name_option.network` |
| PXE lease time | `pxe.lease_time.network` |
| PXE lease enabled | `pxe.lease_enabled.network` |

## Range Profile v1 candidates

Each row is a Range-scoped input. The gateway row has semantic role `DERIVED_LATER`; `pxe.lease_enabled` is `COMPOSITE_LATER`; the remaining inputs are `DIRECT`.

| Input | Source parameter ID |
| --- | --- |
| DHCP lease time | `dhcp.lease_time.range` |
| DNS servers | `dhcp.dns_servers.range` |
| Domain name | `dhcp.domain_name.range` |
| Domain search | `dhcp.domain_search.range` |
| Gateway convention (router evidence) | `dhcp.router.range` |
| NTP servers | `dhcp.ntp_servers.range` |
| BOOTP denied | `dhcp.deny_bootp.range` |
| DDNS enabled | `ddns.enabled.range` |
| DDNS domain | `ddns.domain.range` |
| DDNS generate hostname | `ddns.generate_hostname.range` |
| DDNS update on lease renewal | `ddns.update_on_renewal.range` |
| PXE next server | `pxe.nextserver.range` |
| PXE boot server | `pxe.bootserver.range` |
| PXE bootfile | `pxe.bootfile.range` |
| PXE TFTP server name | `pxe.tftp_server_name.range` |
| PXE bootfile name option | `pxe.bootfile_name_option.range` |
| PXE lease time | `pxe.lease_time.range` |
| PXE lease enabled | `pxe.lease_enabled.range` |

No Range DDNS TTL, fixed-address-update or option-81 parameter is invented: those Range-scoped IDs are absent from the existing specification and are not candidates.

## Workbook and summary

`Profile_Readiness` follows `Overview`, followed by `Profile_Populations`. The follow-on deterministic discovery views (`Profile_Usefulness`, `Profile_Fingerprints`, `Profile_Assignments`, `Profile_KPIs`) then precede `Standardization`, `Decisions`, `Exceptions`, `Grid_Comparison`, `Coverage` and `Manual_Review`. `Profile_Populations` gives descriptive Network and Range population/segment counts and shares without compliance labels. Existing evidence sheets and Overview links to Standardization are retained. The sheets use the existing safe table-writing utilities, without overlapping worksheet and table AutoFilters.

Each input row exposes its profile, identity, semantic role and source parameter alongside required-field status, source population, parameter-applicable population, `Excluded By Applicability`, query counts and coverage, confirmed and explicit not-configured counts, resolved and unresolved percentages, collection/evidence statuses, readiness and reason. Excluded objects are not re-labeled as NOT_CONFIGURED.

A compact Overview summary reports each profile's candidate count and counts of `READY`, `CONDITIONAL`, `NOT_READY`, `DEFERRED` and `NOT_APPLICABLE` inputs, with a drill-down to the matrix. The aggregate **Ready input %** means:

```text
READY inputs / applicable candidate inputs * 100

applicable candidate inputs = candidate inputs - NOT_APPLICABLE inputs - DEFERRED inputs
```

This percentage measures the share of candidate inputs ready for discovery. It is not object coverage, configuration quality or a profile quality score. If no candidates are applicable, a ready-input percentage has no denominator and is not reported as zero.

## Follow-on discovery and future context

These items are documented only as `FUTURE_PROFILE_INPUT`; they have no fabricated readiness rows:

| Future input | Current limit |
| --- | --- |
| Range `server_association_type` as a fingerprint field | Implemented as the Range association family in fingerprint v1 |
| Range `member` association | Collected context; not yet a fingerprint field |
| Range `failover_association` | Collected context; not yet a fingerprint field |
| EA / organizational context | Deferred; no EA correlation in this increment |
| Naming / organizational context | Deferred; no naming-pattern detection in this increment |

Two evidence gaps were controlled before fingerprint v1 was enabled:

1. per-page inheritance response shapes for Network collections that exceed one WAPI page;
2. true unresolved scalar inheritance versus explicit not-configured option absence.

The paging behavior is empirically confirmed: on NIOS 9.x, continuation requests using `_page_id` alone can drop scalar inheritance wrappers from page 2 onward. Reasserting `_inheritance=True` together with `_page_id` restores the effective scalar wrapper representation. The GET-only client therefore reasserts inheritance on every continuation page of an effective query; raw pagination remains unchanged.

The repository includes two read-only diagnostics:

```powershell
python scripts/analyze_inheritance_shapes.py <RAW_DIR> --object-type network

python scripts/probe_inheritance_paging.py `
  --config config/grids.work.yaml `
  --grid LAB `
  --no-verify-tls
```

The first is offline-only and prints wrapper/plain/absent counts per archived page. The second performs GET requests only and prints response-shape counts, never object values, names, refs or continuation tokens. Add `--compare-reassert-inheritance` only when explicitly testing whether reasserting `_inheritance=True` changes page-2 response shape.

A fresh real-LAB collection confirmed the corrected multi-page effective evidence, enabling the deterministic follow-on implementation documented in [Profile fingerprint v1](profile-fingerprint-v1.md). Unresolved core values remain outside normal fingerprints.

Readiness is still not profile usefulness. An input may be 100% resolved and invariant (for example, explicitly not configured everywhere) and therefore READY but non-discriminative. The follow-on `Profile_Usefulness` view reports deterministic variability metrics without converting them into a weighted quality score.

Neither readiness nor fingerprint discovery infers targets, automatic standards, compliance, semantic profile names or remediation. Appliance configuration remains unchanged.

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

The specification contains **21 Network Profile v1 inputs** and **18 Range Profile v1 inputs**. All listed IDs exist in the current parameter specification. Inputs are `DIRECT` except `gateway_convention`, which uses the scope's router parameter with role `DERIVED_LATER`. Readiness assesses the literal router evidence only. No conversion to `FIRST_USABLE`, `LAST_USABLE`, `OTHER_IN_SUBNET` or `OUTSIDE_SUBNET` takes place. PXE inputs remain atomic; no composite PXE interpretation is implemented.

## Evidence and classification

The primary metric is **Resolved Evidence %**, with the scope's **Population Objects** as its denominator:

```text
Resolved Evidence % =
    (Confirmed Objects + Explicit Not Configured) / Population Objects * 100
```

Only explicit parameter evidence counts as `NOT_CONFIGURED`. A missing normalized row remains unresolved. Confirmed Value % alone is insufficient because an explicit not-configured state is also usable evidence.

Classification follows this order:

1. A source row explicitly reporting population zero is `NOT_APPLICABLE`, with reason `No objects in scope`.
2. A hard blocker makes a populated input `NOT_READY`, regardless of its percentage.
3. Otherwise apply the thresholds below to the existing Resolved Evidence %.

| Readiness | Resolved Evidence % |
| --- | --- |
| `READY` | At least 95.0% |
| `CONDITIONAL` | At least 80.0% and below 95.0% |
| `NOT_READY` | Below 80.0% |

Hard blockers are:

- Collection Status: `ERROR`, `PARTIAL` or `UNKNOWN`.
- Required Field Status: `NOT_EXPOSED_BY_WAPI`.
- Evidence Status: `ERROR`, `NOT_EXPOSED_BY_WAPI` or `INSUFFICIENT_DATA`.

A missing source Standardization row cannot prove zero population. It stays `NOT_READY` with a missing-evidence reason; it must not be converted to `NOT_APPLICABLE` or explicit `NOT_CONFIGURED`. Missing or invalid population/resolved metrics and unrecognized statuses are also handled conservatively as `NOT_READY`.

The explicit zero-population rule takes priority even if that source row records a collection error. Its reason retains a warning that the collection status does not confirm an empty scope. This preserves the requested classification without claiming a failed collection established an empty appliance inventory.

Every result preserves the evidence counts and denominators and includes a concise Readiness Reason. A successful object query can coexist with unresolved parameter evidence. Conversely, normalized rows do not override a collection failure.

| Population | Confirmed | Explicit not configured | Unresolved | Resolved evidence | Result with no blockers |
| --- | --- | --- | --- | --- | --- |
| 130 | 127 | 3 | 0 | 100.0% | `READY` |
| 130 | 127 | 0 | 3 | 97.7% | `READY` |
| 130 | 117 | 0 | 13 | 90.0% | `CONDITIONAL` |
| 1000 | 799 | 0 | 201 | 79.9% | `NOT_READY` |

The existing Standardization layer supplies percentages rounded to one decimal place. Readiness uses that supplied metric consistently; it does not recompute a different precision for classification.

### Existing evidence semantics retained

`Evidence Status = PARTIAL` alone is not a hard blocker. For example, complete collection with 97.7% resolved parameter evidence can be `READY`. This differs from `Collection Status = PARTIAL`, which always blocks populated inputs.

`Required Field Status = NOT_EXPOSED_IN_SOME_GRIDS` is also distinct from `NOT_EXPOSED_BY_WAPI`. The former does not introduce an additional blocker beyond the rules above, and the reason flags this partial field availability. The resolved percentage and all original status columns remain visible for review.

Readiness consumes the final parameter-aware Collection Status. Existing Standardization semantics may treat a collector-level partial status caused solely by an unrelated missing field as complete for another parameter when all object evidence was returned and no collection error was recorded. Recorded query failures remain blocking. This increment does not alter that distinction.

## Network Profile v1 candidates

Each row is a Network-scoped input. The gateway row has semantic role `DERIVED_LATER`; all others are `DIRECT`.

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

Each row is a Range-scoped input. The gateway row has semantic role `DERIVED_LATER`; all others are `DIRECT`.

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

`Profile_Readiness` follows `Overview`, before `Standardization`, `Decisions`, `Exceptions`, `Grid_Comparison`, `Coverage` and `Manual_Review`. Existing evidence sheets and Overview links to Standardization are retained. The new sheet uses the existing safe table-writing utilities, without overlapping worksheet and table AutoFilters.

Each input row exposes its profile, identity, semantic role and source parameter alongside required-field status, population, query counts and coverage, confirmed and explicit not-configured counts, resolved and unresolved percentages, collection/evidence statuses, readiness and reason.

A compact Overview summary reports each profile's candidate count and counts of `READY`, `CONDITIONAL`, `NOT_READY` and `NOT_APPLICABLE` inputs, with a drill-down to the matrix. The aggregate **Ready input %** means:

```text
READY inputs / applicable candidate inputs * 100

applicable candidate inputs = candidate inputs - NOT_APPLICABLE inputs
```

This percentage measures the share of candidate inputs ready for discovery. It is not object coverage, configuration quality or a profile quality score. If no candidates are applicable, a ready-input percentage has no denominator and is not reported as zero.

## Future inputs and next increment

These items are documented only as `FUTURE_PROFILE_INPUT`; they have no fabricated readiness rows:

| Future input | Current limit |
| --- | --- |
| Range `server_association_type` | No scope-specific Standardization parameter |
| Range `member` association | No scope-specific Standardization parameter |
| Range `failover_association` | No scope-specific Standardization parameter |
| EA / organizational context | Deferred; no EA correlation in this increment |
| Naming / organizational context | Deferred; no naming-pattern detection in this increment |

The next increment will implement deterministic Network/Range fingerprints **only after this readiness matrix is validated against the real LAB**. Unresolved values must not enter future fingerprints.

This increment creates no fingerprints, clustering, generated profile IDs, profile comparisons, gateway transformations, inferred targets, automatic standards or remediation. It changes no appliance configuration.

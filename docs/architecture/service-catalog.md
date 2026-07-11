# Service catalog

## Purpose

Traceable catalog of 24 microservices from design specs, classified into bootstrap domain areas.

## Scope

Names, domains, P0/P1, owned data. No implementation.

## Current decision

**CONFIRMED** — service names and ownership from Algorithm §6.2 and k3s §2–3.  
**PROPOSED** — mapping into six domain folders below (packaging convenience; planes remain authoritative).

## Domain mapping

### foundation

| Service | P | Owned data |
|---|---|---|
| tenant-control-service | P0 | tenant policy |
| plan-contract-service | P0 | action contracts |
| policy-gate-service | P0 | signed policy decisions |
| audit-ledger-service | P0 | audit log |

### acquisition

| Service | P | Owned data |
|---|---|---|
| repository-intake-service | P0 | repository manifest |
| site-discovery-service | P0 | site inventory |
| chatgpt-observer-service | P0 | observation ledger |

### intelligence

| Service | P | Owned data |
|---|---|---|
| demand-graph-service | P0 | query clusters |
| entity-resolution-service | P0 | entity graph |
| claim-evidence-service | P0 | claim/evidence graph |
| citation-intelligence-service | P0 | citation records |
| absorption-analysis-service | P1 | absorption labels |

### optimization

| Service | P | Owned data |
|---|---|---|
| intervention-generator-service | P0 | intervention candidates |
| digital-twin-service | P1 | model features/predictions |
| portfolio-optimizer-service | P1 | portfolio decisions |

### experimentation

| Service | P | Owned data |
|---|---|---|
| experiment-attribution-service | P1 | experiment results |
| strategy-skill-bank-service | P1 | skill cards |

### platform

| Service | P | Owned data |
|---|---|---|
| forge-console-api | P0 | run metadata |
| agent-orchestrator-service | P0 | workflow state |
| agent-runner-service | P0 | ephemeral run artifacts |
| quality-eval-service | P0 | test/eval evidence |
| artifact-registry-service | P0 | object manifest |
| observability-service | P0 | telemetry |
| engine-adapter-gateway | P0 | adapter config |

**Count:** 24 / 24 — matches design list.

## Apps (not counted in 24)

| App | Role | Status |
|---|---|---|
| operator-console | B부서 UI | NOT IMPLEMENTED |
| api-gateway | external/console edge (PROPOSED) | NOT IMPLEMENTED |

## Unclear / OPEN DECISION boundaries

| Topic | Notes |
|---|---|
| Domain folder vs 4-plane naming | Packaging taxonomy PROPOSED; do not treat folders as runtime plane IDs |
| `forge-console-api` vs `apps/api-gateway` | Split edge vs domain API — OPEN DECISION |
| Event topic names beyond recommended list | Several marked PROPOSED in service READMEs |
| When P1 services emit decision outputs | Feature flags exist; learning telemetry may run earlier (k3s §7) |

## Constraints

- No shared DB table cross-service access
- google/gemini adapters not separate microservices — behind `engine-adapter-gateway` + packages **(CONFIRMED by ADR-0001 accepted 안 A, 2026-07-12 — Algorithm §6.1 문언 해석은 ADR-0001이 보유)**

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §2–3

## Status

CONFIRMED names / PROPOSED domain folders / NOT IMPLEMENTED

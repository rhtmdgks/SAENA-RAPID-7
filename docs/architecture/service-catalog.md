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
| `forge-console-api` vs `apps/api-gateway` | **RESOLVED (ADR-0007)**: v1 edge = forge-console-api 단독. api-gateway는 FUTURE(SaaS) |
| Event topic names beyond recommended list | Several marked PROPOSED in service READMEs |
| When P1 services emit decision outputs | Feature flags exist; learning telemetry may run earlier (k3s §7) |

## v1 토폴로지 — 24 logical capabilities × rendering class (CONFIRMED — ADR-0002 rev.3, 2026-07-12)

용어 (외부 리뷰 R9): "24개 마이크로서비스" = **24 logical capabilities (bounded contexts)** — Gate A 계약 대상, 불변. 배포 형태(rendering)는 별개 운영 결정. **Worker host 2종은 배포 아티팩트 — capability로 세지 않음.**

| Rendering class | 수 | 구성 |
|---|---|---|
| Independent Deployment | 8 | control 6: forge-console-api, plan-contract, policy-gate, agent-orchestrator, audit-ledger(RBAC 상위 tier), tenant-control / artifact-registry / engine-adapter-gateway |
| Worker-hosted module | 10 | intelligence-worker: demand-graph, entity-resolution, claim-evidence, citation-intelligence, absorption-analysis(off) / **optimization-worker**: intervention-generator, digital-twin(off), portfolio-optimizer(off), experiment-attribution, strategy-skill-bank(off) — own schema + 모듈별 DB credential(논리 경계 — 보안 경계 아님) + 경계 이벤트 규칙(dependency-policy 9~13) |
| Job | 5 | runner pool: agent-runner, repository-intake, quality-eval (SA 3분리) / browser pool: chatgpt-observer, site-discovery |
| Merged infra capability | 1 | observability → OTel Collector + 기성 스택 (계약·책임 유지, 구현체 기성) |
| Future capability | — | api-gateway(SaaS), google-generative-search, gemini |

합계 8+10+5+1 = 24. 총 Deployment 10 = independent 8 + worker host 2 (compute pool). measurement-worker 추출 트리거는 ADR-0002 rev.3 참조.

## Constraints

- No shared DB table cross-service access
- google/gemini adapters not separate microservices — behind `engine-adapter-gateway` + packages **(CONFIRMED by ADR-0001 accepted 안 A, 2026-07-12 — Algorithm §6.1 문언 해석은 ADR-0001이 보유)**

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §2–3

## Status

CONFIRMED names / PROPOSED domain folders / NOT IMPLEMENTED

# API and event contracts

## Purpose

Contract-first and event-contract-first rules before any implementation.

## Scope

gRPC/Protobuf internal APIs; versioned events; JSON Schema Action Contract.

## Current decision

**CONFIRMED (포맷은 ADR-0008로 v1 개정)**

- Internal API: ~~gRPC + Protobuf~~ → **v1 = OpenAPI + JSON** (ADR-0008, 2026-07-12 — k3s §1 편차를 ADR가 보유. Proto/gRPC는 측정 트리거 충족 시 별도 ADR로 재도입)
- External console API: REST/GraphQL as required
- Events: versioned topics; at-least-once; idempotent consumers — **AsyncAPI + 공통 JSON Schema** (ADR-0008)
- Action Contract·서명 계약: JSON Schema validated; human approval required
- **JSON↔Proto 이중 매핑 v1 제거** (ADR-0008)

## Required event envelope fields (CONFIRMED — 예외 처리는 ADR-0006 대기)

`event_id`, `tenant_id`, `run_id`, `schema_version`, `producer`, `occurred_at`, `trace_id`, `idempotency_key`

**해소됨 (ADR-0006 rev.2, 2026-07-12) — 3-context envelope 모델**:

| Context | 대상 | envelope 규칙 |
|---|---|---|
| TenantContext | tenant-scoped raw 이벤트 | `tenant_id` 필수 |
| SystemContext | global metadata (`tenant.policy.updated.v1`, `adapter.config.updated.v1`, `slo.alert.fired.v1`) | `tenant_id`·`run_id` 면제 |
| AggregateContext | cross-tenant Strategy Card (`strategy.card.eligible.v1`) | `tenant_id` 제거. 필수: `aggregate_scope_id`, `cohort_size`, `privacy_threshold`(미달 시 발행 금지), `de_identification_status` |

원 tenant lineage = 접근 제한(audit role) audit-ledger reference로만. event schema 구현 가능.

`engine_id` (PROPOSED, 2026-07-12 감사): observation·citation·experiment 계열 이벤트에 엔진 차원 필드 추가 — v1 단일 엔진에서도 "Google/Gemini 이벤트 존재 시 즉시 탐지" 감사 능력 확보, 멀티엔진 확장 시 재버전 회피.

## Service dependency 표기 규약 (PROPOSED — 감사 H-5 해소)

service README의 `Upstream dependencies` / `Downstream consumers`는 **호출·소비 방향 기준**으로 통일:

- Upstream = 내가 호출하거나 그 산출물(이벤트·계약)을 소비하는 대상
- Downstream = 나를 호출하거나 내 산출물을 소비하는 대상
- 라이브러리 패키지(`packages/*`)는 런타임 consumer 아님 — 이 필드 기재 금지 (코드 의존은 dependency-policy.md 소관)

## Recommended topics (CONFIRMED list from design)

- `repo.intaken.v1`
- `site.inventory.completed.v1`
- `demand.graph.versioned.v1`
- `observation.captured.v1`
- `citation.normalized.v1`
- `plan.contract.proposed.v1`
- `plan.contract.approved.v1`
- `patch.unit.completed.v1`
- `quality.gate.passed|failed.v1`
- `experiment.outcome.observed.v1`
- `strategy.card.eligible.v1`

Additional topics in service READMEs marked **PROPOSED**.

## 신규 토픽 후보 (PROPOSED — 2026-07-12 감사)

| Topic | 목적 | 근거 |
|---|---|---|
| `workspace.destroyed.v1` | per-run workspace TTL 파기 증명 — "TTL destroy 100%" SLO 감사 가능화 | sec Q8 |
| `deployment.confirmed.v1` | 고객 배포 완료 = 7일 measurement clock 시작 조건의 이벤트화 | aeo F10, Algorithm §7.3 |
| `policy.decision.recorded.v1` | policy-gate README에 이미 존재하던 토픽 — 카탈로그 등재 (boot B6) | ADR-0003 |
| `experiment.outcome.observed.v1`에 `outcome_layer` 판별자 필드 | B 계층(≥2 독립 signal layer) vs C 지표 분리 — skill-bank는 B 검증 통과 outcome만 소비 | aeo F4, sec E3 |

## Core business identifiers (document now; schemas later)

All core data contracts MUST be able to carry:

- `tenant_id`
- `workspace_id`
- `project_id`
- `site_id`
- `run_id`
- `actor_id`

## Provider interface candidates (PROPOSED names; no code yet)

- `CrawlerPolicy`
- `RetrievalEligibility`
- `QueryGenerator`
- `ProbeRunner`
- `CitationExtractor`
- `VisibilityScorer`
- `TelemetryConnector`
- `OptimizationPolicy`
- `AnswerExtractor` (PROPOSED 추가, 2026-07-12 감사 — absorption 추출 인터페이스. citation≠absorption 원칙과 인터페이스 세트의 비대칭 해소. CrawlerPolicy/RetrievalEligibility 경계 정의도 필요)

## Constraints

- No silent breaking changes; compatibility tests under `packages/contracts` / `events`
- Single owner for contracts/schemas/events/migrations

## Open decisions

- ~~Exact protobuf package naming~~ — 이연 (ADR-0008; proto/ 예약·비움)
- ~~AsyncAPI vs protobuf-only for events~~ — **확정 (ADR-0008/0011)**: AsyncAPI 3.0 + JSON Schema 2020-12. envelope 구체(9필드·3-context·engine_id 닫힌 enum) = ADR-0013, 호환성 = ADR-0012

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §1, §4
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5.2, §6.3

## Status

CONFIRMED principles / NOT IMPLEMENTED schemas

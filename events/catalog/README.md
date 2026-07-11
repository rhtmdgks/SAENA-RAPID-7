# Event catalog

## Purpose

Human-readable catalog of versioned events.

## Scope

Bootstrap lists recommended + proposed topics.

## Current decision

### CONFIRMED (design recommended)

| Topic | Producer (typical) |
|---|---|
| repo.intaken.v1 | repository-intake-service |
| site.inventory.completed.v1 | site-discovery-service |
| demand.graph.versioned.v1 | demand-graph-service |
| observation.captured.v1 | chatgpt-observer-service |
| citation.normalized.v1 | citation-intelligence-service |
| plan.contract.proposed.v1 | plan-contract-service |
| plan.contract.approved.v1 | plan-contract-service |
| patch.unit.completed.v1 | agent-runner-service |
| quality.gate.passed.v1 / failed.v1 | quality-eval-service |
| experiment.outcome.observed.v1 | experiment-attribution-service |
| strategy.card.eligible.v1 | strategy-skill-bank-service |

### PROPOSED (service READMEs; not yet in design topic list)

tenant.policy.updated.v1, audit.event.appended.v1, entity.graph.versioned.v1, claim.evidence.versioned.v1, absorption.analyzed.v1, intervention.candidates.ready.v1, prediction.scored.v1, portfolio.selected.v1, workflow.state.changed.v1, artifact.registered.v1, adapter.config.updated.v1, slo.alert.fired.v1, run.created.v1, policy.decision.recorded.v1 (boot B6 — policy-gate README 기존 선언의 등재 누락 수정)

### PROPOSED 추가 (2026-07-12 감사)

workspace.destroyed.v1 (TTL 파기 증명), deployment.confirmed.v1 (7일 clock 시작 조건) — 근거·목적은 `docs/architecture/api-event-contracts.md` 신규 토픽 표 참조.

**ADR-0006 rev.2 accepted (2026-07-12)**: envelope 규칙 확정 — **3-context 모델** (TenantContext/SystemContext/AggregateContext). strategy.card 등 cross-tenant 이벤트는 AggregateContext(tenant_id·run_id 금지 + k-anonymity 필드 + lineage_audit_ref). 구체 필드·판별 방식·`event_type` 9번째 필드·`engine_id` 닫힌 enum은 **ADR-0013** 참조. schema 구현 가능 (W1).

> 정정 기록 (2026-07-12, W0 T16): 본 절의 이전 문구("8필드 유지, strategy.card는 payload 필터")는 폐기된 ADR-0006 **rev.1** 결정문의 잔재였음 — rev.2가 권위.

## Constraints

Schema files go under `events/schemas/` (future).

## Open decisions

- Finalize PROPOSED topics via ADR before implementation

## Source specification references

- Algorithm §6.3

## Status

CONFIRMED core list / PROPOSED extensions / NOT IMPLEMENTED schemas

# events/schemas

## Purpose

Machine-readable event schemas (future).

## Scope

One schema per topic version.

## Current decision

NOT IMPLEMENTED.

## Constraints

- Envelope = 3-context 모델 (ADR-0006 rev.2 → 구체화 **ADR-0013**): TenantContext(tenant_id 필수) / SystemContext(tenant_id·run_id 금지) / AggregateContext(tenant_id·run_id 금지 + aggregate_scope_id·cohort_size·privacy_threshold·de_identification_status·**lineage_audit_ref**)
- 공통 9필드 (k3s 8필드 + `event_type` — 편차 기록은 ADR-0013 보유), `engine_id` = 닫힌 enum `["chatgpt-search"]`
- 파일 배치: `events/schemas/<domain>/<topic-without-version>/v<major>/schema.json`, 이벤트명 `<domain>.<entity>.<action>.v<major>` (ADR-0011/0013)
- `cohort_size ≥ privacy_threshold`는 스키마 표현 불가 — 발행측 런타임 게이트 필수 (ADR-0013, W2A 실장)
- 경계 이벤트는 transactional outbox 경유 (ADR-0002 rev.3)

## Open decisions

- ~~Format choice~~ — **확정 (ADR-0008)**: AsyncAPI + 공통 JSON Schema

## Source specification references

- k3s §4

## Status

NOT IMPLEMENTED

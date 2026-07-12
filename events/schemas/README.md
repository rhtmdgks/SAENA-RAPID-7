# events/schemas

## Purpose

Machine-readable event schemas (future).

## Scope

One schema per topic version.

## Current decision

**포인터 전용 (W1 확정)**: 이벤트 스키마의 수기 SSOT는 `packages/contracts`(ADR-0011)다 — payload = `packages/contracts/json-schema/event/<name>/v<major>/`, 채널 조합 = `packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml`. **본 디렉토리에 수기 스키마 반입 금지.** 아래 Constraints의 `events/schemas/<domain>/...` 배치 규칙은 ADR-0011 SSOT 확정 이전 문구로 효력 없음(ADR-0024 기록). 본 디렉토리는 향후 파생 미러 또는 폐기 대상 — W2C 이벤트 버스 배선 시 재결정.

## Constraints

- Envelope = 3-context 모델 (ADR-0006 rev.2 → 구체화 **ADR-0013**): TenantContext(tenant_id 필수) / SystemContext(tenant_id·run_id 금지) / AggregateContext(tenant_id·run_id 금지 + aggregate_scope_id·cohort_size·privacy_threshold·de_identification_status·**lineage_audit_ref**)
- 공통 9필드 (k3s 8필드 + `event_type` — 편차 기록은 ADR-0013 보유), `engine_id` = 닫힌 enum `["chatgpt-search"]`
- ~~파일 배치: `events/schemas/<domain>/...`~~ — **무효 (W1, ADR-0024)**: 배치는 packages/contracts 소관(위 Current decision). 이벤트명 규약 `<domain>.<entity>.<action>.v<major>`은 유지 (ADR-0013)
- `cohort_size ≥ privacy_threshold`는 스키마 표현 불가 — 발행측 런타임 게이트 필수 (ADR-0013, W2A 실장)
- 경계 이벤트는 transactional outbox 경유 (ADR-0002 rev.3)

## Open decisions

- ~~Format choice~~ — **확정 (ADR-0008)**: AsyncAPI + 공통 JSON Schema

## Source specification references

- k3s §4

## Status

NOT IMPLEMENTED

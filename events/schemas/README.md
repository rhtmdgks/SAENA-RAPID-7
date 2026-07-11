# events/schemas

## Purpose

Machine-readable event schemas (future).

## Scope

One schema per topic version.

## Current decision

NOT IMPLEMENTED.

## Constraints

- Envelope = 3-context 모델 (ADR-0006 rev.2): TenantContext(tenant_id 필수) / SystemContext(면제) / AggregateContext(tenant_id 제거 + aggregate_scope_id·cohort_size·privacy_threshold·de_identification_status)
- 경계 이벤트는 transactional outbox 경유 (ADR-0002 rev.3)

## Open decisions

- ~~Format choice~~ — **확정 (ADR-0008)**: AsyncAPI + 공통 JSON Schema

## Source specification references

- k3s §4

## Status

NOT IMPLEMENTED

# packages/contracts

## Purpose

Versioned API contracts (service interfaces).

## Scope

Single-owner contract definitions. Protected path. 구획: `json-schema/` + `openapi/` + `asyncapi/` (`proto/`는 예약 — ADR-0008 재도입 트리거 충족 전 비움).

## Current decision

CONFIRMED need; contents NOT IMPLEMENTED.
**v1 포맷 (ADR-0008, 2026-07-12)**: 도메인·서명 = JSON Schema / 동기 = OpenAPI+JSON / 이벤트 = AsyncAPI+JSON Schema. JSON↔Proto 이중 매핑 제거. Proto/gRPC는 측정 트리거(p99·직렬화 CPU·streaming·다언어 SDK) 충족 시 별도 ADR.

## Constraints

- Breaking changes require ADR + compatibility tests
- Must accept tenant/workspace/project/site/run/actor IDs
- P0 계약 12종 (Synthesis rev.2 §7): Tenant/Actor/Workspace/Project/Site/Run Context + SourceSnapshot, ChangePlan, ApprovalDecision, PatchArtifact, VerificationResult, AuditEvent

## Open decisions

- ~~Proto package naming~~ — 이연 (ADR-0008)
- OpenAPI/JSON Schema 네이밍 규약 — Wave 1 착수 시

## Source specification references

- k3s §4

## Status

NOT IMPLEMENTED

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

## Ownership (ADR-0011)

본 디렉토리가 **유일한 수기 편집 계약 SSOT**다 (단일 owner = Contracts Steward). `packages/schemas`는 파생(codegen) 산출 전용 — 수기 스키마 반입 금지.

## Open decisions

- ~~Proto package naming~~ — 이연 (ADR-0008)
- ~~OpenAPI/JSON Schema 네이밍 규약~~ — **확정 (ADR-0011, 2026-07-12)**: JSON Schema 2020-12 단일 방언, `$id = https://schemas.the-saena.ai/{category}/{name}/v{major}/…`, directory-per-major + `registry.json` + git tag `contracts/{name}/vX.Y.Z`. 호환성 정책 = ADR-0012, envelope = ADR-0013.

## Source specification references

- k3s §4; ADR-0011/0012/0013

## Status

NOT IMPLEMENTED

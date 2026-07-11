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

## Registry (ADR-0011 Open 종결, W1)

`registry.schema.json`이 `registry.json`(계약당 1 엔트리)을 지배한다. 전 필드는 JSON Schema `additionalProperties:false`로 봉인되며, entry 저작·판정 권한은 Contracts Steward 단독(ADR-0011/0012 단일 owner 원칙)이다.

필드 의미(1줄):

- `name` — 파일 slug(kebab-case), 디렉토리명과 일치.
- `catalog_name` — `docs/architecture/contract-catalog.md` 12계약 행 역참조. **`compat_class`/`signed`와 무관한 별도 축** — 예: RunContext 1개 카탈로그 행이 2개 파일(run-context-lifecycle/run-context-experiment)로 분할되며 둘 다 `catalog_name: "RunContext"`를 공유한다(ruling R10, 12계약↔13파일 매핑).
- `category` — `envelope\|context\|domain\|event\|common`, `$id`/경로의 category 세그먼트와 일치.
- `compat_class` — 호환성 정책 클래스(ADR-0012): `closed`(모든 변경 major) / `open`(payload 점진 진화) / `frozen`(envelope, 변경 시 신규 ADR 필수). **스키마 진화 규칙 축**.
- `signed` — 사람 서명 계약(ChangePlan/ApprovalDecision)만 `true`. **`compat_class`와 독립된 별도 boolean 축**(ruling R6) — closed이면서 signed가 아닌 계약이 다수 존재(예: SourceSnapshot).
- `format` — `json-schema\|openapi\|asyncapi`.
- `major` — 메이저 버전, `v{major}` 경로 세그먼트와 일치.
- `full_version` — 현재 릴리스 semver(`X.Y.Z`); `major`는 이 값의 첫 세그먼트와 일치해야 한다(관계 제약, harness 검증).
- `$id` — non-resolvable 식별자, 파일 경로와 1:1(ADR-0011 스킴).
- `owner` — 단일 owner role slug.
- `status` — entry lifecycle: `draft`(스키마 저작 완료, 태그 이전) → `active`(최초/후속 릴리스 태그 시점) → `deprecated`(후속 major로 대체 후).
- `frozen_authority_adr` — `compat_class: frozen`일 때만 required, envelope 필드셋을 승인한 ADR(예: ADR-0013).

관계 제약(name+major 유일성, full_version↔major 접두 일치, $id↔파일 1:1, category↔$id 경로 세그먼트 일치)은 JSON Schema로 표현 불가하여 `tests/contract/validate/test_registry.py`(W1 harness)가 집행한다 — `packages/observability/registry/attributes.schema.json` 선례와 동형 처리.

`registry.json`은 W1-01 시점에는 정직한 빈 배열이다 — 각 스키마 unit이 자신의 entry를 동일 커밋에 추가한다(atomicity, ADR-0011).

## Open decisions

- ~~Proto package naming~~ — 이연 (ADR-0008)
- ~~OpenAPI/JSON Schema 네이밍 규약~~ — **확정 (ADR-0011, 2026-07-12)**: JSON Schema 2020-12 단일 방언, `$id = https://schemas.the-saena.ai/{category}/{name}/v{major}/…`, directory-per-major + `registry.json` + git tag `contracts/{name}/vX.Y.Z`. 호환성 정책 = ADR-0012, envelope = ADR-0013.
- ~~`registry.json`의 스키마(자체 JSON Schema 검증 대상 여부)~~ — **확정 (본 unit, w1-01)**: `registry.schema.json`으로 검증(ADR-0011 §Open decisions 종결).

## Source specification references

- k3s §4; ADR-0011/0012/0013

## Status

NOT IMPLEMENTED

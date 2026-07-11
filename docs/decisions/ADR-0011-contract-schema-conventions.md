# ADR-0011: Contract schema conventions — JSON Schema 2020-12, $id scheme, layout, validation toolchain

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

ADR-0008(JSON Schema family 확정)을 실행 가능한 컨벤션으로 구체화한다: 방언, `$id` 체계, 디렉토리 레이아웃, 레지스트리, 검증 툴체인, codegen 원칙.

## Scope

In: JSON Schema/OpenAPI/AsyncAPI 방언 버전, `$id` 스킴, `packages/contracts` 디렉토리 구조, `registry.json` 필드, 계약 검증·lint 도구 선택, codegen 원칙(도구 확정은 제외).
Out: 개별 계약 스키마 파일 작성(W1), 호환성 정책(ADR-0012), envelope 필드(ADR-0013), datamodel-code-generator 최종 채택 여부(W1 entry spike).

## Context

- ADR-0008이 v1 계약 포맷을 JSON Schema(서명·도메인) / OpenAPI+JSON(동기) / AsyncAPI+JSON Schema(이벤트) 3-패밀리로 확정했으나 방언 버전·`$id`·레이아웃은 미결이었다.
- `$id` 도메인은 사용자가 2026-07-12 `schemas.the-saena.ai`(보유 도메인)로 확정했다 — 이 식별자는 **non-resolvable**(실제 HTTP 조회 대상 아님, 순수 네임스페이스)이며 파일 경로와 1:1 대응한다.
- JSON Schema 2020-12은 OpenAPI 3.1과 방언이 정렬되어 `$ref` 무변환 공유가 가능하다(draft-07은 OpenAPI 3.1과 비정렬). `unevaluatedProperties`는 envelope `oneOf` 봉인(ADR-0013)에 필요하며 draft-07에는 없다.
- 팀 구성(AI agent + 인간 owner 1인)에서 검증 스택 이원화(Python+Node 풀스택)는 유지비를 배가시킨다. ADR-0009가 Python 3.12 + uv를 primary로 확정했으므로 계약 검증도 Python 우선이 정합적이다. 단 AsyncAPI 3.0의 Python validator는 상호 검토에서 부재가 확인되어 `@asyncapi/cli`(Node)만 예외로 허용한다 — 이 Node 사용은 ADR-0009의 "Node는 계약·CI lint 도구 전용" 경계 및 contract-lint-only 격리 원칙(devcontainer 내 명시적 용도 제한)과 동형이다.
- codegen 도구(datamodel-code-generator)의 JSON Schema 2020-12 지원, 특히 `unevaluatedProperties`와 envelope `oneOf` 조합에 대한 지원 수준은 미검증 상태다. 언어 확정(ADR-0009)이 이 선결정을 순서상 앞선다.

## Current decision

**방언**: JSON Schema **2020-12** 단일 방언. 모든 스키마 파일의 `"$schema"` 키는 `https://json-schema.org/draft/2020-12/schema`이며 **파일의 첫 번째 key**여야 한다(lint rule로 강제, W1 harness에 포함). 동기 API는 **OpenAPI 3.1**, 비동기 이벤트는 **AsyncAPI 3.0**.

**`$id` 스킴**:

```
https://schemas.the-saena.ai/{category}/{name}/v{major}/{name}.schema.json
```

- `category` ∈ `envelope | context | domain | event | common`
- 도메인 `the-saena.ai`는 사용자 보유 도메인(2026-07-12 확정) — **non-resolvable identifier**로만 사용, 실제 스키마 서빙 엔드포인트가 아니다.
- `$id` 경로는 파일시스템 경로와 **1:1 매핑**된다(레지스트리 없이도 파일 위치를 `$id`에서 역산 가능).

**디렉토리 레이아웃 (directory-per-major)**:

```
packages/contracts/json-schema/<category>/<name>/v<major>/<name>.schema.json
packages/contracts/openapi/<name>/v<major>/openapi.yaml
packages/contracts/asyncapi/<name>/v<major>/asyncapi.yaml
```

메이저 버전마다 디렉토리를 분리한다 — 동시에 여러 메이저를 병행 서빙해야 하는 호환성 정책(ADR-0012)의 전제 구조.

**레지스트리**: `packages/contracts/registry.json`에 계약당 1 엔트리 — 필드: `name`, `category`, `major`, 전체 semver(`full_version`, 예: `1.3.0`), `$id`, `owner`, `status`(draft|active|deprecated). 릴리스마다 git tag `contracts/{name}/vX.Y.Z`를 병행 발급한다(ADR-0012 호환성 harness가 tag 기준 N-1 example 검증에 사용).

**SSOT 경계 (사용자 결정 2026-07-12)**: `packages/contracts`가 **유일한 수기 편집(hand-edited) SSOT**다. `packages/schemas`는 codegen·파생 산출물 전용이며 직접 편집을 금지한다(향후 보호 경로 README 정정 대상, T16).

**검증 툴체인**:

| 대상 | 도구 | 언어 |
|---|---|---|
| JSON Schema 2020-12 | check-jsonschema / jsonschema | Python |
| OpenAPI 3.1 | openapi-spec-validator | Python |
| AsyncAPI 3.0 | `@asyncapi/cli` | **Node(유일 예외)** |

Node 사용은 devcontainer 내 "계약 lint 전용"으로 격리한다(ADR-0009의 contract-lint-only isolation 원칙 준수) — 서비스 코드나 CI 일반 파이프라인에 Node 런타임을 확산시키지 않는다.

**codegen 원칙**: schema-first — **생성된 타입만 사용, 수기 타입 작성 금지**. 구체 도구(datamodel-code-generator) 채택은 **W1 entry spike**로 이연한다: 2020-12 방언, 특히 `unevaluatedProperties`와 envelope `oneOf` 조합(ADR-0013)에 대한 지원 수준을 검증한 뒤 확정한다. spike 실패 시 대안 도구 재평가 또는 부분 수기 fallback을 별도 ADR로 기록한다.

## Constraints

- `"$schema"`가 첫 key가 아닌 스키마 파일은 CI lint에서 fail.
- `$id`를 실제 네트워크 조회 대상으로 사용하는 코드(런타임 리졸버 fetch 등)는 금지 — non-resolvable 원칙 위반.
- `packages/schemas` 직접 편집 금지 — 전부 codegen 파이프라인 산출물.
- Node 런타임은 AsyncAPI CLI 실행 외 계약 검증 경로에 도입하지 않는다.
- 디렉토리 레이아웃·`$id` 스킴 변경은 전 계약 재발급을 수반하므로 본 ADR 개정 없이 임의 변경 금지.

## Open decisions

- datamodel-code-generator 최종 채택 여부 및 버전 — W1 entry spike 결과로 확정.
- AsyncAPI 3.0 Node 도구의 air-gap/오프라인 캐시 전략 — 위험 잔존, 별도 조치 필요.
- `registry.json`의 스키마(자체 JSON Schema 검증 대상 여부) — W1에서 확정.

## Source specification references

- `docs/decisions/ADR-0008-v1-contract-format.md` (포맷 패밀리 확정)
- `docs/decisions/ADR-0009-language-stack.md` (Python primary, Node 격리 원칙)
- `docs/architecture/contract-catalog.md` (계약 카탈로그, 포맷 매핑)
- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §2–11

## Status

accepted (2026-07-12, 사용자)

> 검증 기록: independent critic conformance review PASS (2026-07-12) — 사용자 G2 처리 지침("계획·결정 부합 시 사전 승인")의 조건 충족 확인.

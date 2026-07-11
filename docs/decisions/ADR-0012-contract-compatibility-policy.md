# ADR-0012: Contract compatibility policy — dual policy, envelope frozen, single harness

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

계약 변경이 언제 breaking(major)인지, 하위 호환을 어떻게 자동 검증하는지 확정한다.

## Scope

In: 서명 계약/이벤트 payload/envelope 각각의 호환성 규칙, enum 변경 판정, backward compatibility 검증 방법, harness 소유권 분리.
Out: 개별 스키마 파일(W1), envelope 필드 목록 자체(ADR-0013), `registry.json`/git tag 메커니즘 세부(ADR-0011에서 정의됨 — 본 ADR은 그 위에서 harness가 어떻게 소비하는지만 다룬다).

## Context

- 계약군은 성격이 다르다: 사람이 서명하는 계약(ChangePlan, ApprovalDecision 등, ADR-0008 "도메인·사람 서명 계약")은 완전성이 생명이고, 이벤트 payload는 프로듀서·컨슈머 독립 배포를 전제로 점진 진화가 필요하다. 단일 정책으로는 둘 다 과도하거나 과소 제약된다.
- 상호 검토에서 enum 변경 판정이 정정되었다: 최초안은 "축소만 major, 확장은 minor(tolerant-read 전제)"였으나, enum **확장**도 구 consumer 입장에서는 미지(unknown) 값을 만나는 forward-incompatible 변경이므로 **축소·확장 모두 major**로 정정한다. `engine_id`처럼 enum 확장 자체가 재승인 대상(엔진 추가 = 별도 ADR)인 필드는 이 원칙과 감사 취지가 정합한다.
- 계약 harness를 이원 구현(예: architecture 팀 자체 구현 + testing 팀 별도 구현)하면 판정 불일치·유지비 배가가 발생한다 — 상호 검토에서 단일 구현으로 통합 합의.
- oasdiff는 OpenAPI 전용 구조 diff 도구로, JSON Schema/AsyncAPI 커버리지가 없어 주력이 될 수 없다 — 보조 탐지기로만 채택.

## Current decision

**이원 호환성 정책**:

| 계약 유형 | 정책 | 규칙 |
|---|---|---|
| **서명 계약** (closed) | `additionalProperties: false` | **모든 변경 = major** (필드 추가·제거·타입 변경·enum 변경 불문) |
| **이벤트 payload** (open) | 점진 진화 허용 | optional 필드 추가 = **minor**. required 필드 추가, 타입 축소(narrowing), 의미 변경(semantic change) = **major** |
| **envelope** (frozen) | 동결 | 어떤 변경도 **새 ADR** 필요 (ADR-0013이 v1을 확정; 필드 추가/제거/의미 변경은 ADR-0013 개정 또는 후속 ADR) |

**enum 규칙 (이벤트 payload 내)**: **축소(narrowing)와 확장(widening) 모두 major.** 확장이 minor가 아닌 이유 — 구 consumer가 신규 enum 값을 받으면 처리 불능(forward-incompatible)이기 때문이다. 이는 "확장=minor, tolerant-read 전제 허용"이라는 최초 초안을 상호 검토에서 정정한 결과다.

**consumer unknown-enum tolerant-read**: 위 major 판정과 별개로, consumer가 미지 enum 값을 만났을 때 오류 없이 안전 처리(예: fallback 분기)하는 tolerant-read 동작은 **계약 테스트의 필수 케이스**로 강제한다. 이는 enum 확장을 minor로 허용하는 면죄부가 아니라 **defense-in-depth**다 — major 버전 롤아웃 중 구·신 consumer 혼재 기간의 안전망 역할.

**Backward compatibility 1차 보장**: "새 스키마가 N-1 버전 인스턴스를 계속 accept한다"를 1차 보장 목표로 삼는다. 이는 breaking 여부의 실질적 판정 기준이며, 아래 compat test가 이를 자동 검증한다.

**Compatibility test (single harness)**:

1. **직전 tag(N-1) example 전건 valid** — `registry.json` + git tag `contracts/{name}/vX.Y.Z`(ADR-0011)로 식별한 직전 태그의 예시 인스턴스들을 신규 스키마로 재검증, 전건 pass해야 backward compat 주장 가능.
2. **구조 diff로 금지된 변경 탐지** — major 없이 발생한 금지 변경(예: `additionalProperties:false` 계약의 필드 추가, required 필드 신규 추가, enum 값 변경)을 major bump 누락 여부와 함께 탐지. JSON Schema/AsyncAPI가 주력 대상.
3. **oasdiff는 OpenAPI 전용 보조 탐지기** — JSON Schema/AsyncAPI 커버리지 밖의 OpenAPI 세부(경로·파라미터 변경 등)를 보완.

**Harness 소유권 분리**:

- **판정 규칙·`registry.json`·git tag 발급 권한 = Contracts Steward 단독** (ADR-0011의 단일 owner 원칙과 동일 라인).
- **harness 코드·fixture·CI 배선 = testing/QA ownership** — **단일 구현**(이원 구현 금지). Steward는 규칙을 정의하고 testing이 이를 코드로 집행한다.

## Constraints

- envelope 변경은 본 ADR이나 ADR-0011이 아니라 **반드시 새 ADR**을 거친다 — 동결 원칙 위반 사례 없음.
- 서명 계약에 `additionalProperties: true`를 두는 것은 금지 — closed 정책 위반.
- enum 변경(축소/확장 불문)을 minor로 태그하는 것은 CI compat test에서 fail로 취급.
- harness 이원 구현(동일 판정을 두 개의 독립 코드베이스로 재구현) 금지.

## Open decisions

- backward compat 보장 기간(N-1만인지 N-2까지 확장할지)은 실사용 데이터 축적 후 재검토.
- oasdiff 외 AsyncAPI 전용 구조 diff 보조 도구 도입 여부 — 필요성 미확인.

## Source specification references

- `docs/decisions/ADR-0008-v1-contract-format.md`
- `docs/decisions/ADR-0011-contract-schema-conventions.md` (`$id`/레이아웃/`registry.json`/git tag 메커니즘)
- `docs/architecture/contract-catalog.md` (버전 관리 원칙 — additive-only + breaking major bump + compatibility test)
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5, §9–10

## Status

accepted (2026-07-12, 사용자)

> 검증 기록: independent critic conformance review PASS (2026-07-12) — 사용자 G2 처리 지침("계획·결정 부합 시 사전 승인")의 조건 충족 확인.

# ADR-0009: v1 language stack — Python 3.12 + uv single primary

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G1 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

implementation-waves.md W0의 "언어 스택 OPEN"을 종결하고 W1(계약 12종) entry 조건을 충족한다.

## Scope

In: services/**·packages/**·workflows/**의 구현 언어, 런타임 버전, 패키지 매니저.
Out: monorepo task 툴링(ADR-0010), 계약 검증 툴체인(ADR-0011), operator-console 프론트엔드 스택(구현 착수 시 별도 결정).

## Context

- ADR-0008이 proto/gRPC를 이연 — proto codegen 툴체인이 언어 선택을 구속하지 않음.
- W4~W5 워크로드(intelligence-worker의 embedding·entity resolution, optimization-worker의 DiD measurement)는 Python 생태계(scipy/statsmodels 계열)가 사실상 유일한 합리적 선택.
- W2B Temporal은 Python SDK 성숙. W4 chatgpt-observer는 Playwright for Python 공식 지원.
- ADR-0002 rev.3의 모듈 경계(worker 내 동거 모듈 직접 import 금지)는 import-linter로 CI 강제 가능 — dependency-policy 규칙 11 이행 수단.
- 팀 = AI agent + 인간 owner 1인: polyglot은 계약 codegen·CI·devcontainer·lint 표면을 배가.

## Current decision

| 항목 | 결정 |
|---|---|
| Primary 언어 | **Python 3.12** (`.python-version` 고정; 3.13 승격은 주요 데이터 라이브러리 wheel 안정화 확인 후 별도 판단) |
| 패키지 매니저 | **uv** — 단일 `uv.lock`, `uv sync --locked`가 CI 정합 게이트 |
| 타입 규율 | 계약 파생 타입은 codegen 산출물만(수기 타입 금지 — ADR-0011), 서비스 코드는 type hint + mypy(strict는 packages/domain부터 단계 적용) |
| TypeScript | `apps/operator-console` **한정 예약** — 구현 착수 시 pnpm 도입, 서비스 코드 침투 금지 (경계는 import-linter + 리뷰로 강제) |
| Node 런타임 | 계약·CI lint 도구 실행 **전용** (AsyncAPI CLI 등 — ADR-0011), 서비스 코드에 미사용 |
| Go/gRPC | ADR-0008 재도입 트리거 충족 시 핫패스 한정 재검토 (별도 ADR) |

## Constraints

- 의존성 추가는 dependency-policy 규칙(핀 필수, allowlist) 준수 — uv.lock 무단 변경은 CI `uv sync --locked` 실패로 검출
- W1 entry에 codegen spike 필수: datamodel-code-generator의 JSON Schema 2020-12(`unevaluatedProperties`, oneOf envelope) 지원 검증 후 codegen 도구 확정

## Open decisions

- mypy strict 적용 범위 확대 시점 (packages/domain 실코드 등장 후)
- operator-console 스택 상세 (구현 착수 Wave에서)

## Source specification references

- `docs/architecture/implementation-waves.md` (W0 잔여: 언어 스택)
- `docs/decisions/ADR-0008-v1-contract-format.md` (proto 이연 — 언어 결정 순서 논거)
- `docs/decisions/ADR-0002-contract-unit-vs-deployment-unit.md` (모듈 경계 강제 요구)
- `docs/architecture/dependency-policy.md` 규칙 5·11

## Status

accepted (2026-07-12, 사용자 — Wave 0 계획 G1 사전 승인)

# ADR-0010: Monorepo tooling — uv workspaces + just + import-linter, build-graph 도구 이연

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G1 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

implementation-waves.md W0의 "monorepo 툴링 OPEN"을 종결한다. ADR-0008과 동일한 "이연 + 측정 트리거" 패턴을 build-graph 도구에 적용한다.

## Scope

In: workspace 의존성 그래프, task runner, 모듈 경계 강제, build-graph 캐싱 도구의 도입 여부.
Out: CI 플랫폼·파이프라인 구조(ADR-0018), 언어(ADR-0009).

## Context

- W0~W1 실산출물 = 문서·JSON Schema·호환성 테스트 — build 캐싱 이득이 측정 불가 수준.
- Nx/Turborepo는 JS 패키지 그래프 전제(Python은 3rd-party plugin 의존). Bazel은 인간 1인 운영에 유지비 과다. moonrepo는 polyglot이나 Python toolchain 상대적 미성숙.
- dependency-policy §Allowed directions와 규칙 7(그래프 사이클 정적 검증)은 선언적 계약 파일로 강제 가능해야 함.

## Current decision

| 항목 | 결정 |
|---|---|
| Workspace | **uv workspaces** — member = `packages/*` + `services/*/*` + `workflows` + `apps/*`(future). 서비스별 `pyproject.toml` = 의존성 선언 |
| Task runner | **just** (루트 `justfile`) — `setup`/`lint`/`typecheck`/`test`/`contracts-validate`/`dev-up`/`worktree-*`/`verify`. `just verify` = 로컬 단일 게이트, CI와 동일 명령 |
| 모듈 경계 | **import-linter** (`.importlinter`) — dependency-policy 허용 방향 + ADR-0002 동거 모듈 격리를 CI 정적 검증 |
| Build-graph 도구 | **도입하지 않음.** 재도입 트리거(아래) 충족 시 별도 ADR — moonrepo 1순위 재평가 |
| Affected-only | 초기 = 경로 기반 job skip(dorny/paths-filter, ADR-0018). graph 기반 전환은 트리거 연동 |

**재도입 트리거 (측정 가능):**
1. CI 전체 wall-time > 10분 (캐시 적용 후 기준)
2. affected-only graph 실행 필요 (활성 서비스 30+ 또는 경로 필터 오탐이 반복 실측)
3. TS workspace 실도입 (operator-console 착수)
4. contract-compat job 시간이 CI 최장 job 등극 (상호 검토 추가분)

## Constraints

- uv.lock 단일 lockfile — workspace member의 개별 lockfile 금지
- `just verify`와 CI 파이프라인의 명령 동일성 유지 (드리프트 = ADR-0018 위반)

## Open decisions

- 트리거 충족 시 moonrepo vs pants 재평가 (해당 시점 생태계 기준)

## Source specification references

- `docs/architecture/implementation-waves.md` (W0 잔여: monorepo 툴링)
- `docs/architecture/dependency-policy.md` §Allowed directions, 규칙 7·11
- `docs/decisions/ADR-0008-v1-contract-format.md` (이연+트리거 패턴 선례)

## Status

accepted (2026-07-12, 사용자 — Wave 0 계획 G1 사전 승인)

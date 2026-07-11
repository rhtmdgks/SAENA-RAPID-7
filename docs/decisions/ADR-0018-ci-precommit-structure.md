# ADR-0018: CI & pre-commit structure

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

CI 플랫폼·소유 경계·파이프라인 구조를 확정하여 T17(Integrator 단독 CI 조립)이 각 팀의
`tools/validation/ci-jobs/` 조각을 무결정 통합할 수 있게 한다.

## Scope

In: CI 플랫폼 선택, 워크플로 파일 구성, stage 순서, 소유 경계, pre-commit 프레임워크
정책, Actions 핀·캐시·affected-only 전략, branch protection 활성화, self-verification
프로토콜.
Out: 각 gate의 판정 내용(ADR-0017 coverage/harness, 보안 ADR의 secret-scan/SBOM 세부),
hook 스크립트 자체 구현(별도 security ADR 계열).

## Context

- `.github/workflows/**`는 루트 `workflows/`(Temporal, protected path — CLAUDE.md 보호
  경로 목록)와 이름이 유사해 혼동 위험이 있다 — 계획 §7 위험 6에서 명시적으로 지적됨.
  **`.github/workflows/`는 CI 전용이며 Temporal 정의를 절대 포함하지 않는다.**
- 계획 §1 상호 검토에서 3팀 동시 `.github` 생성 시도가 worktree-ownership 위반으로
  기각되고 **Integrator 단독 소유**로 합의됨 — CLAUDE.md 원칙 6(독점 수정 경로) 적용
  사례.
- CLAUDE.md 원칙 10(배포·push·merge 금지)에 따라 CI는 검증만 수행하고 배포/게시
  단계를 포함할 수 없다.
- 사용자 확정(2026-07-12): branch protection + required checks는 **W0 즉시 활성화**
  (GitHub 설정 자체는 인간이 변경, required checks 목록은 T17 산출물).

## Current decision

| 항목 | 결정 |
|---|---|
| 플랫폼 | **GitHub Actions만** — `.github/workflows/` 하위. 루트 `workflows/`(Temporal
  workflow 정의, protected path)와 혼동 금지, 리뷰·커밋 메시지에서 상호 경고 |
| 소유 경계 | `.github/workflows/**`, `.pre-commit-config.yaml`, `CODEOWNERS` = **Integrator
  단독**(CLAUDE.md 원칙 7 준용). 각 팀은 `tools/validation/ci-jobs/<team>-<job>.yml`
  job 조각으로만 handoff — 직접 `.github` 편집 금지 |
| 워크플로 구성 | 2개 파일: `ci.yml`(lint/schema-validate/unit/contract-compat) +
  `security.yml`(guards/secret-scan/SBOM/policy-symmetry/zizmor — pr-guards 흡수) |
| Stage 순서 | `guards → lint → schema-validate → secret-scan → unit → contract-compat →
  SBOM`. 앞 4단계(guards/lint/schema-validate/secret-scan)는 **병렬 fan-out** |
| Pre-commit | 프레임워크(uv tool install pre-commit)로 관리. hook은 **repo:local +
  language:system 우선**, 3rd-party hook repo는 **full commit SHA rev pin**일 때만
  허용. 원칙: **"pre-commit은 편의, CI가 권위"** — 단 secret-scan은 예외로 로컬에서도
  반드시 차단(누출 예방은 사후 검증보다 사전 차단이 우선) |
| Actions 핀 | 전 Action **full commit SHA pin** + zizmor lint(워크플로 보안 정적 분석) |
| 캐시 | `actions/cache`, key = `uv.lock` 해시 + 도구 바이너리 버전 |
| Affected-only | 초기 = `dorny/paths-filter`(경로 기반). graph 기반 전환은 ADR-0010
  재도입 트리거 연동(build-graph 도구 도입 시점과 동기화) |
| Branch protection | **W0 즉시 활성화**(사용자 확정 2026-07-12). GitHub 설정 변경
  자체는 인간이 수행, **required checks 목록은 T17 산출물**로 제출 |
| Self-verification 프로토콜 | CI는 배선 후 3종 증거로 자가 검증: ① scaffold(빈/기본
  상태)에서 전 stage green ② planted-violation fixture 3종(schema syntax error /
  `docs/specs/**` 수정 시도 / fake-secret canary) 각각 **해당 stage에서만** fail —
  다른 stage로 false-positive 전파 없음 ③ 워크플로 정의에 push/deploy/publish step이
  전무함을 grep으로 증명 |

## Constraints

- CI 워크플로에 배포·push·publish step을 두지 않는다(CLAUDE.md 원칙 10, 계획 §6
  rollback 절 "continue-on-error 눕히기는 advisory 금지 원칙 위반" 준용 — required
  check를 advisory로 되돌리는 것은 명시적 rollback 절차 없이는 금지)
- `.github/workflows/**` 변경은 Integrator 외 어떤 agent/worktree도 직접 수정 불가
  (T04를 포함한 본 worktree도 ADR 문서만 다루며 워크플로 파일 자체는 생성하지 않음)
- `just verify`(ADR-0010)와 CI 명령의 동일성 유지 — 드리프트는 본 ADR 위반
- rollback: required check 목록에서 제거(이력 보존) → workflow revert 순서, 무단
  `continue-on-error` 삽입으로 사실상 무력화하는 방식 금지

## Open decisions

- required checks 정확한 목록(=T17 산출물, 팀별 ci-jobs 조각 확정 후)
- affected-only graph 기반 전환 시점(ADR-0010 트리거 4종과 연동)
- security.yml의 policy-symmetry 체크 세부 스크립트 경로(보안 ADR 계열에서 확정)

## Source specification references

- `docs/architecture/implementation-waves.md` (W0 잔여: CI/pre-commit 구조)
- `docs/decisions/ADR-0010-monorepo-tooling.md` (`just verify` 동일성, affected-only
  경로 기반 초기값)
- CLAUDE.md 보호 경로 목록 (`workflows/` vs `.github/workflows/` 구분), 원칙 6·7·10

## Status

accepted (2026-07-12, 사용자 — Wave 0 계획 G2 사전 승인, branch protection 즉시
활성화 결정 포함)

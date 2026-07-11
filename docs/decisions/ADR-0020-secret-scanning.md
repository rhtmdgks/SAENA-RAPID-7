# ADR-0020: Secret scanning — gitleaks 3-point coverage + verified-secret runbook

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

이 저장소의 secret 유입을 세 지점에서 차단하고, 유출 발생 시 인간이 따를 runbook을 확정한다.

## Scope

In: gitleaks 설정·baseline·allowlist 규칙, 3개 실행 지점(pre-commit/CI/SessionStart hook), 테스트 fixture 정책, verified-secret 대응 절차.
Out: trufflehog 등 2차 검증 계층의 상시 활성화(옵트인 대상, 아래 명시), FORGE 런타임(고객 tenant) secret 관리(security-model.md 소관).

## Context

- 계획 §1 "Secret scanning" 항목: gitleaks는 단일 바이너리·의존성 0·언어 무관이라 언어 확정(ADR-0009) 이전에도 도입 가능하다.
- ADR-0019의 hook 5종 중 `secret-scan.sh`(SessionStart)는 staged/uncommitted 변경만 스캔한다 — 전체 git 이력 스캔은 시간·비용상 세션 hook에 부적합하며 CI가 담당한다.
- SECURITY.md는 GitHub Private Vulnerability Reporting을 1차 보고 채널로 이미 CONFIRMED — 이 ADR은 그 위에 secret 전용 절차를 얹는다.
- worktree-ownership.md: write 권한·secret·Git token은 per-patch-unit lease로 발급 — 유출 시 회전 대상은 이 lease 경로를 따른다.

## Current decision

### 3개 실행 지점 (primary = gitleaks)

| 지점 | 범위 | 시점 |
|---|---|---|
| pre-commit | staged diff | commit 직전, 로컬 |
| CI (`security.yml`) | full-history | PR/push마다, 권위 지점 |
| Claude SessionStart hook | staged/uncommitted만 | 세션 시작 시, dev-repo 보호(ADR-0019 hook 5) |

초기 full-history 스캔에서 empty baseline이 나오는 것으로 "현재 zero"를 확인한다.

### Allowlist 정책

- `.gitleaksignore`는 **fingerprint 단위 항목만** 허용 — 경로 단위(`packages/foo/**`) allowlist는 금지. 경로 allowlist는 그 경로 전체를 영구 무검사로 만들어 오탐 회피가 실제 유출을 가리는 것을 방지한다.
- allowlist 추가는 PR 경유 + security CODEOWNERS 리뷰 필수 — 단독 merge 금지.

### 테스트 fixture 정책

- gitleaks 탐지 테스트용 secret-형 문자열은 **저장소에 커밋하지 않는다.**
- harness가 런타임에 AKIA 형식 등 canary를 scratch 디렉토리에 생성해 사용(T09 검증 절차: 런타임 canary 생성→add→pre-commit fail 확인→즉시 폐기).
- planted-violation 테스트(의도적 secret 삽입 시나리오)는 test 브랜치 또는 sandbox 저장소에서만 실행 — main/worktree에 잔존 금지.

### Verified-secret runbook (SECURITY.md 절 추가)

실제 유출 secret이 확인되면 순서대로:

1. **즉시 회전** — 해당 credential을 발급 시스템에서 폐기·재발급 (git 이력 정리보다 선행).
2. **보고** — GitHub Private Vulnerability Reporting으로만(공개 Issue/Discussion 금지, SECURITY.md 기존 CONFIRMED 채널).
3. **이력 정리는 인간 전용 결정** — `git filter-repo` 등은 force-push를 요구하므로 CLAUDE.md 원칙 10(배포·push·merge 금지)에 의해 agent 수행 금지. 실행 여부·시점은 인간이 결정.
4. **audit 기록** — fingerprint + rule-id + path만 기록, **secret 값 자체는 절대 기록하지 않는다.**

### trufflehog (opt-in, 비활성 기본)

`trufflehog --only-verified`는 후보 문자열을 외부 provider로 전송해 검증하는 방식이라 egress 정책과 긴장 관계에 있다. 주간 CI 2차 계층으로 **사용자 opt-in 시에만** 활성화 — 기본값은 비활성.

## Constraints

- gitleaks는 W1 이전에도 즉시 도입 가능(언어 무관) — 언어 결정(ADR-0009) 대기 불필요.
- CI full-history 스캔이 권위 지점, pre-commit/SessionStart는 보조.
- audit 로그(ADR-0019 hook 4)는 secret redaction 통과 후에만 기록 — 이 규칙과 동일 원칙 적용.

## Open decisions

- trufflehog opt-in 활성화 시점 및 egress 대상 provider 목록 확정 — 사용자 결정 대기(계획 §8-15).

## Source specification references

- `SECURITY.md` (GitHub Private Vulnerability Reporting, protected concerns)
- `docs/architecture/security-model.md` (allowlist가 본체 원칙, C-1)
- `docs/architecture/worktree-ownership.md` (per-patch-unit secret lease)
- `docs/decisions/ADR-0019-w0-dev-repo-safety-hooks.md` (SessionStart hook 5)

## Status

accepted (2026-07-12, 사용자 — Wave 0 계획 G2 사전 승인)

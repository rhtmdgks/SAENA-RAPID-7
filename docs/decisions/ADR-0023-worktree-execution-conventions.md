# ADR-0023: Worktree execution conventions

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G1 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

worktree-ownership.md의 CONFIRMED 규칙("1 write agent = 1 worktree = 1 patch unit")을 이 저장소의 구체 실행 규약으로 확정하고, 동 문서의 Open decision(".saena 경로 네이밍 PROPOSED")을 종결한다.

## Scope

In: 개발 모노레포의 worktree 물리 경로·unit-id·브랜치 네이밍·`.saena/` 런타임 조정 상태·생명주기·소유권 선언.
Out: 고객 source runner ephemeral workspace(W3에서 runner가 구현 — 본 ADR은 경로 형식만 예약), patch-unit secret lease(worktree-ownership.md 소관).

## Context

- worktree-ownership.md CONFIRMED: 1 write agent → 1 worktree → 1 patch unit, Integrator만 충돌 해결, Plan Mode agent는 write 금지.
- AGENTS.md Lead 역할이 "run manifests under `.saena`"를 전제하나 경로 규약 미확정.
- worktree를 repo 내부에 두면 다른 agent의 glob·lint·테스트 수집이 오염됨.

## Current decision

| 항목 | 규약 |
|---|---|
| 물리 경로 | 저장소 **형제** 디렉토리 `../SAENA-RAPID-7.worktrees/<unit-id>/` (repo 내부 배치 금지) |
| unit-id | `w<wave>-<seq2>-<slug>` — 예: `w0-02-worktree-adr`. wave = 착수 Wave, seq2 = 2자리 순번, slug = kebab-case 요약 |
| 브랜치 | `unit/<unit-id>` — 1 branch = 1 patch unit = 1 PR |
| seq 발번 | Lead 단일 창구 — `.saena/worktrees/registry.json` 기준 (동시 발번 race 방지) |
| `.saena/` (repo 루트, gitignored) | `runs/<run_id>/manifest.yaml` (run manifest), `worktrees/registry.json` (unit-id → 경로 → owner agent → exclusive path globs), `locks/` |
| 소유권 선언 | worktree 생성 시 exclusive path glob을 registry에 기록. 기존 항목과 겹침 발견 시 생성 거부 — Integrator만 override |
| 생명주기 | patch unit merge 또는 폐기 시 `tools/development/worktree.sh destroy <unit-id>` = `git worktree remove` + registry 해제. 잔존 검출 = `just worktree-audit` |
| Integrator | 다중 unit 브랜치의 main 반영·충돌 해소는 Integrator 역할 단독. 원격 push는 어떤 경우에도 없음 (CLAUDE.md 원칙 10) |
| runner ephemeral (W3 예약) | `/workspace/<tenant_id>/<run_id>/` — PLANNED, W3 runner 구현 시 확정 |

`.saena/`는 gitignore 대상이되 secret-scan 스캔 범위에는 포함한다 (registry·manifest에 secret 유입 금지).

대안 기각: repo 내부 `.worktrees/`(gitignore) — glob 오염은 막을 수 있으나 lint·검색 도구의 재귀 순회 비용과 실수 표면이 남음. 단일 디스크 볼륨 제약 환경의 fallback으로만 문서화.

## Constraints

- No two write agents own same file without Integrator assignment (worktree-ownership.md 불변)
- Plan Mode agent는 worktree 생성 불가 (write 금지의 파생)
- worktree 내에서도 protected paths 규칙·hook 게이트 동일 적용

## Open decisions

- `.saena/worktrees/registry.json`의 파일 lock 방식 (W0는 "발번 = Lead 단일 창구" 운영 규칙으로 완화, 도구적 lock은 후속)

## Source specification references

- `docs/architecture/worktree-ownership.md` (CONFIRMED 규칙 + Open decision 종결 대상)
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §9.2
- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §7

## Status

accepted (2026-07-12, 사용자 — Wave 0 계획 G1 사전 승인)

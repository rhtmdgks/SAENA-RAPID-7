# Worktree ownership

## Purpose

Exclusive file ownership rules for MAS write agents.

## Scope

Customer source worktrees and monorepo development worktrees.

## Current decision

**CONFIRMED**

- One write agent → one worktree → one patch unit
- Integrator Agent only resolves conflicts
- Plan Mode agents: no write
- Customer remote write tokens not injected before human approval

## 감사·합성 보강 (2026-07-12 — CONFIRMED 설계)

- **per-patch-unit secret lease**: write 권한·secret·Git token은 unit 단위 발급 (승인 1회 = 전체 해금 금지 — H-7). 전 lease는 policy-gate 경유.
- unit 간 의존 순서(TAG dependencies)는 orchestrator가 강제 — lease 순서가 dependency graph 위반 불가.
- 고위험 unit 2인 승인.
- workspace 파기 증명: `workspace.destroyed.v1` audit event — "TTL destroy 100%" SLO화.
- 개발 저장소 측: Claude↔Cursor 상호 보호 대칭 (CLAUDE.md Protected paths ↔ .cursor/rules), Cursor bootstrap 예외 RETIRED.

## Constraints

- No two write agents own same file without Integrator assignment
- Ephemeral workspace destroyed after Job TTL
- Rollback unit required per patch unit + rollback 동작 검증 gate (testing-strategy.md)

## Open decisions

- ~~Worktree path naming convention~~ — **확정 (ADR-0023, 2026-07-12)**: 형제 디렉토리 `../<repo>.worktrees/<unit-id>` + 브랜치 `unit/<unit-id>` + `.saena/` registry (`tools/development/worktree.sh`). runner ephemeral `/workspace/<tenant_id>/<run_id>/`는 W3 PLANNED

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §9.2
- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §7

## Status

CONFIRMED rules / NOT IMPLEMENTED runner

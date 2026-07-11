# CONTRIBUTING

## Purpose

기여·변경 절차 최소 규칙 (bootstrap).

## Scope

이 monorepo의 문서/골격/향후 구현 변경.

## Current decision

PROPOSED contribution flow. CI/CD not yet implemented.

## Constraints

1. 설계 원본 `docs/specs/SAENA_*_v1.md` **수정 금지** (새 ADR/architecture 문서로 제안).
2. contract/schema/event/migration 변경은 단일 owner + ADR.
3. Cursor는 소범위만; 보호 경로는 Claude Code + 인간 승인.
4. 비밀정보·실 API key commit 금지.
5. Agent는 git push / merge / deploy 금지.

## Workflow (PROPOSED)

1. 관련 spec + architecture 문서 읽기
2. ADR 초안 (경계/계약 변경 시)
3. Plan / Action Contract (고객 run) 또는 개발 PR 설명
4. contract tests 우선
5. independent review
6. 인간 merge

## Open decisions

- Branch protection rules — OPEN DECISION
- CODEOWNERS final mapping — **활성 `CODEOWNERS` 존재** (2026-07-12; `.example` 삭제). teams 생성 + branch protection 활성화 전까지 선언적

## Source specification references

- Design specs under `docs/specs/`
- `docs/architecture/dependency-policy.md`; `agent-authority-boundaries.md`

## Status

PROPOSED

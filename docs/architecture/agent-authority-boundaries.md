# Agent authority boundaries — Cursor vs Claude Code

## Purpose

Cursor와 Claude Code의 수정 범위·권한 경계를 단일 문서로 정리. 감사 발견(비대칭 2건) 반영.

## Scope

개발 저장소 편집 권한 경계 (고객 run의 MAS 역할은 `.claude/agents/**` + worktree-ownership.md).

## Current decision (CONFIRMED)

### Cursor (소범위)

- **허용**: 문서 정리, 파일/디렉토리 스캐폴딩, 오타, 주석, 소규모 UI, 단일 파일 명확 리팩터, 계약 미변경 테스트 보충 (`.cursor/rules/10-cursor-scope.mdc`)
- **금지**: 서비스 경계·API/이벤트 계약·DB schema·AuthZ/tenant 격리·Temporal·k3s/Helm/RBAC/NetworkPolicy·AEO scoring·evidence 정책 변경, 배포·push·merge
- **에스컬레이션 (Claude Code로)**: 3파일 초과, 2+ 서비스 영향, `packages/contracts|schemas`·`events`·`workflows`·`deploy` 변경, 보안·격리 영향, 아키텍처 판단
- **보호 경로**: `docs/specs/**`, `packages/contracts|schemas/**`, `events/**`, `workflows/**`, `deploy/**`, `.claude/**`, migration, AuthN/Z (`20-protected-paths.mdc`)
- **Bootstrap 예외**: **RETIRED** (2026-07-12, commit e763070 이후 — 전면 적용)

### Claude Code (광범위 — 단 대칭 보호)

- **허용**: 다파일·계약·아키텍처 작업 (인간 승인 게이트 하)
- **금지 (역방향 보호 — 감사 F-10 반영, CLAUDE.md Protected paths)**: `.cursor/rules/**` 완화, `docs/specs/**`, `packages/contracts|schemas/**`, `events/**`, `workflows/**`, `deploy/**`, ADR Status 임의 변경(accepted 전환은 인간만), `.claude/settings*.json` permissions 완화

### 대칭성

Cursor는 `.claude` 완화 금지 ↔ Claude Code는 `.cursor/rules` 완화 금지 — 한쪽이 상대 경계를 해제 불가 (단방향 구멍 해소, 감사 Q14 비대칭 1).

## Constraints

- 어느 host도 인간 승인 없이 보호 경로 수정·상대 host 경계 완화 불가
- CODEOWNERS(활성) + branch protection(OPEN)이 최종 강제 — 문서 규칙은 관행

## Open decisions

- branch protection 규칙 (CONTRIBUTING.md) — OPEN DECISION
- Codex host 적용 시 동등 경계 (AGENTS.md `.codex`)

## Source specification references

- `.cursor/rules/10-cursor-scope.mdc`, `20-protected-paths.mdc`, `30-validation.mdc`; `CLAUDE.md` Protected paths; Prompt pkg §10 host adapter map; 감사 Q14

## Status

CONFIRMED 경계 / branch protection NOT IMPLEMENTED

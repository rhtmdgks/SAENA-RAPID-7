# .claude/

## Purpose

Claude Code harness skeleton: agents, commands, hooks, skills, settings example.

## Scope

Directory layout + TODOs only. Full agent markdown bodies deferred.

## Current decision

Layout aligned with B-department prompt package host adapter map. subagent 정의 14종 IMPLEMENTED (문서), hook·command·skill은 설계 문서 단계.

## Layout

- `agents/research/` — discovery/demand/evidence/citation-competition/technical-risk/planner (**정의 완료**)
- `agents/implementation/` — technical-patch/content-compiler/schema/integrator (**정의 완료**)
- `agents/review/` — test/fidelity-critic/security-critic/independent-release-reviewer (**정의 완료**)
- `commands/` — 5단계 slash-command 매핑 설계 (스텁 Wave 3)
- `hooks/` — hook 이벤트 매핑 + 설정 예시 (**미배선·미동작** — README 명시)
- `skills/` — SAENA 의무 skill 목록 (SKILL.md 미작성)
- `settings.example.json` — **예시 전용** (실제 활성 = `settings.local.json`, gitignored). permissions.deny 17규칙은 예시이며 복사·검토 전 무효

## 활성 vs 예시 구분 (정직 표기)

| 파일 | 성격 | 강제력 |
|---|---|---|
| `settings.example.json` | 예시 | 없음 (복사 전) |
| `settings.local.json` | 로컬 활성 (gitignored) | plan 모드 + deny(있을 때) |
| `hooks/**` | 설계 문서 | **없음 (스크립트·배선 부재)** |
| `agents/**` | 역할 선언 | 없음 (런타임 lease는 hook/Policy Gate 소관) |

## Constraints

- Do not relax security settings without Security + Lead approval
- Hooks are not a complete security boundary — k3s Policy Gate remains authoritative
- 설계 문서를 "활성"으로 표현 금지

## Open decisions

- Hook 스크립트 구현 (Wave 3) / host별 차이 (Claude vs Codex vs Cursor)

## Source specification references

- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §3, §10–11
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §8–10

## Status

NOT IMPLEMENTED (skeleton only)

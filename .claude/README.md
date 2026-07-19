# .claude/

## Purpose

Claude Code harness skeleton: agents, commands, hooks, skills, settings example.

## Scope

Directory layout + TODOs only. Full agent markdown bodies deferred.

## Current decision

Layout aligned with B-department prompt package host adapter map. subagent 정의 14종 IMPLEMENTED (문서), W0 dev-repo hook 5종 IMPLEMENTED, **skill 16종 IMPLEMENTED (Wave 6)**; command·FORGE runtime hook ladder는 설계 문서 단계.

## Layout

- `agents/research/` — discovery/demand/evidence/citation-competition/technical-risk/planner (**정의 완료**)
- `agents/implementation/` — technical-patch/content-compiler/schema/integrator (**정의 완료**)
- `agents/review/` — test/fidelity-critic/security-critic/independent-release-reviewer (**정의 완료**)
- `commands/` — 5단계 slash-command 매핑 설계 (스텁 Wave 3)
- `hooks/` — W0 dev-repo 안전 hook 5종 **구현·배선 완료** (scripts/ + settings.json — ADR-0019); FORGE runtime ladder는 W3
- `skills/` — SAENA 의무 skill **16종 IMPLEMENTED** (SKILL.md + `manifest.json` SSOT + skill-manifest/skill-quality/skill-bundle/plugin-sync 검증; `saena-skill-pack` 플러그인 패키징) — Wave 6
- `settings.example.json` — 예시 (역사 보존). deny 17규칙은 **체크인 `settings.json`으로 승격 완료** (2026-07-12, 사용자 승인)

## 활성 vs 예시 구분 (정직 표기)

| 파일 | 성격 | 강제력 |
|---|---|---|
| `settings.json` (체크인) | **활성** | plan 모드 + deny 17 + hook 5종 (신규 세션부터) |
| `settings.example.json` | 예시 (역사) | 없음 |
| `settings.local.json` | 로컬 오버라이드 (gitignored) | 개인 설정 |
| `hooks/scripts/**` | **활성 스크립트 (W0 5종)** | PreToolUse deny/ask + PostToolUse audit + SessionStart scan |
| `skills/**` (16 SKILL.md + manifest.json) | **활성 선언 + 검증** | skill-manifest/skill-quality/skill-bundle 게이트; 런타임 강제는 W0 hook + 사람 검토 (FORGE runtime ladder = W3) |
| `agents/**` | 역할 선언 | 없음 (런타임 lease는 hook/Policy Gate 소관) |

## Constraints

- Do not relax security settings without Security + Lead approval
- Hooks are not a complete security boundary — k3s Policy Gate remains authoritative
- 설계 문서를 "활성"으로 표현 금지

## Open decisions

- FORGE runtime hook ladder (Wave 3) / host별 차이 (Claude vs Codex vs Cursor)

## Source specification references

- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §3, §10–11
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §8–10

## Status

W0 안전 hook 5종 + deny 승격 IMPLEMENTED·배선 (2026-07-12); agents 정의 문서 완료; **skill 16종 IMPLEMENTED (Wave 6, 2026-07-19)**; commands·FORGE runtime hook ladder = W3

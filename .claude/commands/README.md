# .claude/commands/

## Purpose

SAENA FORGE 5단계 slash command 스텁. 각 단계 프롬프트는 `prompts/`에 verbatim 존재 (ADR-0007 D-7) — command는 해당 프롬프트를 로드하는 얇은 진입점 설계.

## Status

**설계 (NOT IMPLEMENTED).** command 스텁 파일 미작성 — 본 README가 매핑 설계. 실제 command md는 Wave 3에서 prompts/ 참조로 작성.

## 매핑

| Command | 단계 | 권한 | 로드 프롬프트 | agent |
|---|---|---|---|---|
| /saena-bootstrap | Preflight | read-only | prompts/bootstrap.md | (host adapter) |
| /saena-plan | Plan | read-only | prompts/plan.md | research/* → planner-agent |
| /saena-execute | Approved Execution | contract 범위 write | prompts/execution.md | implementation/* |
| /saena-verify | Independent Review | read-only | prompts/verification.md | review/* |
| /saena-handoff | Handoff | 생성 전용 | prompts/handoff.md | (forge-console-api) |

## Constraints

- /saena-execute는 signed `action-contract.json` 존재 시에만 유효 (Policy Gate·hook 강제 — NOT IMPLEMENTED). command 존재가 게이트를 대체하지 않음.
- 엔진 스코프 ChatGPT Search only 전 단계 유지.

## Source specification references

- Prompt pkg §0 (4단계 표), §4–9; ADR-0007; prompts/README.md

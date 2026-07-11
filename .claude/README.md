# .claude/

## Purpose

Claude Code harness skeleton: agents, commands, hooks, skills, settings example.

## Scope

Directory layout + TODOs only. Full agent markdown bodies deferred.

## Current decision

PROPOSED layout aligned with B-department prompt package host adapter map.

## Layout

- `agents/research/` — Discovery / Demand / Evidence / Citation research roles (TODO)
- `agents/implementation/` — Technical / Content / Schema / Integrator write roles (TODO)
- `agents/review/` — Test / Fidelity / Security critics (TODO)
- `commands/` — slash-command stubs (TODO)
- `hooks/` — SessionStart / PreToolUse / PostToolUse policies (TODO)
- `skills/` — SAENA portable skills (TODO; see design mandatory skill list)
- `settings.example.json` — example settings only

## Constraints

- Do not relax security settings without Security + Lead approval
- Hooks are not a complete security boundary — k3s Policy Gate remains authoritative

## Open decisions

- Exact agent file names and model routing
- Hook implementation host differences (Claude vs Codex)

## Source specification references

- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §3, §10–11
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §8–10

## Status

NOT IMPLEMENTED (skeleton only)

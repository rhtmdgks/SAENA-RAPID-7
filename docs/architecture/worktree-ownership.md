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

## Constraints

- No two write agents own same file without Integrator assignment
- Ephemeral workspace destroyed after Job TTL
- Rollback unit required per patch unit

## Open decisions

- Worktree path naming convention — PROPOSED `.saena` / runner ephemeral paths TBD

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §9.2
- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §7

## Status

CONFIRMED rules / NOT IMPLEMENTED runner

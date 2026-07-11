# Testing strategy

## Purpose

Test-first layers for contracts, agents, and package readiness.

## Scope

unit / contract / integration / e2e / security / performance (+ eval fixtures).

## Current decision

**CONFIRMED** quality gates list from Algorithm §11.1.  
**PROPOSED** directory layout under `tests/`.

## Layers

| Layer | Intent |
|---|---|
| unit | pure domain logic (future) |
| contract | protobuf/json-schema/event compatibility |
| integration | service + bus + db testcontainers (future) |
| e2e | synthetic tenant Plan→Approve→Patch→Handoff |
| security | injection, secret, deploy-temptation fixtures |
| performance | runner/browser quotas, gate latency |

## Completion categories (CONFIRMED)

AEO correctness; patch correctness; safety; reproducibility; measurement; business integrity

## Constraints

- Critical gates cannot be skipped
- Independent critic required for release
- No external lift claims without registered evidence

## Open decisions

- Coverage thresholds — OPEN DECISION
- Browser harness vendor details — OPEN DECISION

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §11
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §10–11
- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §12

## Status

CONFIRMED gate intent / NOT IMPLEMENTED suites

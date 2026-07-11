# System context

## Purpose

Describe SAENA FORGE as internal B-department package and RAPID-7 algorithm boundary.

## Scope

Actors, planes, external systems, explicit exclusions.

## Current decision

**CONFIRMED**

- Product: RAPID-7 (algorithm) + FORGE (harness)
- Operator: SAENA internal B department on k3s
- v1 engine: ChatGPT Search only
- Customer deliverable: source patch / branch / draft PR / evidence bundle — **not** deployment

## System context (logical)

```text
B부서 Operator
    → Forge Console (apps/operator-console + forge-console-api)
        → Control plane (tenant, plan-contract, orchestrator, policy, audit)
        → Intelligence / Optimization / Experimentation services
        → Acquisition (intake, discovery, chatgpt observer)
        → Execution (agent-runner Jobs, quality-eval, artifacts)
    → Customer source (isolated workspace only)
    → External: approved LLM providers, approved Git host, ChatGPT observation path

OUT OF SCOPE (v1 agents): production deploy, CMS publish, git push, DNS/live robots change
OUT OF SCOPE (v1 engine activation): Google AI Overviews, AI Mode, Gemini
```

## Four planes (CONFIRMED naming from k3s spec)

1. Control plane
2. Intelligence plane
3. Execution plane
4. Measurement plane

Bootstrap domain folders (`foundation`, `acquisition`, …) are a **PROPOSED** packaging taxonomy mapped onto these planes — see service-catalog.md.

## Constraints

- Algorithm code must not embed deployment-profile specifics
- Provider adapters isolated under `packages/provider-adapters/`
- Central API must not directly mutate customer code (runner workspace only)

## Open decisions

- Exact north-south API gateway shape (`apps/api-gateway`) — PROPOSED placeholder
- Graph store Neo4j vs Postgres graph — OPEN DECISION (spec: P1)

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §0, §6
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3

## Status

CONFIRMED context / NOT IMPLEMENTED software

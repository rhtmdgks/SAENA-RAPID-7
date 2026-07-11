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

## v1 Rendering (CONFIRMED — ADR-0002 rev.3, 2026-07-12)

4-plane은 논리 구조, 물리 배치는 rendering class로 표현: 24 logical capabilities = Independent Deployment 8 + worker-hosted module 10 (intelligence-worker / optimization-worker, compute pool) + Job 5 + merged infra 1(observability). v1 edge = forge-console-api 단독 (api-gateway는 FUTURE/SaaS — ADR-0007). 상세: service-catalog.md rendering 표.

## Constraints

- Algorithm code must not embed deployment-profile specifics — featureFlags 분기는 gateway/plan-contract 경계만 (dependency-policy 8)
- Provider adapters isolated under `packages/provider-adapters/` — 관측 계약은 엔진 중립 `PlatformObservation`(+engine_id, ADR-0007)
- Central API must not directly mutate customer code (runner workspace only)

## Open decisions

- ~~api-gateway shape~~ — RESOLVED (ADR-0007: FUTURE/SaaS)
- Graph store Neo4j vs Postgres graph — OPEN DECISION (spec: P1; 소유·projection 규칙은 확정 — data-ownership.md)

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §0, §6
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3

## Status

CONFIRMED context / NOT IMPLEMENTED software

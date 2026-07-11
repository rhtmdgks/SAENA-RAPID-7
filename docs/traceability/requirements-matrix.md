# Requirements traceability matrix

## Purpose

Map bootstrap artifacts to design requirements.

## Scope

Bootstrap scaffolding coverage only.

## Current decision

PROPOSED matrix for scaffolding verification.

| Requirement | Source | Bootstrap artifact | Status |
|---|---|---|---|
| 24 microservices named | Algorithm §6.2 | `services/**`, service-catalog.md | CONFIRMED mapping / NOT IMPLEMENTED code |
| ChatGPT Search only v1 | All specs | CLAUDE.md, adapters, feature flags docs | CONFIRMED docs |
| Google/Gemini deferred | All specs | provider-adapters PLANNED | CONFIRMED boundary |
| Action Contract / human approval | Algorithm §5; Prompt pkg | CLAUDE.md, AGENTS.md | CONFIRMED principles |
| Event topics | Algorithm §6.3 | api-event-contracts.md, events/ | CONFIRMED list / NOT IMPLEMENTED schemas |
| k3s Helm package | k3s spec | deploy/ | Skeleton only |
| Tenant isolation | Algorithm §6.1; k3s | tenancy-model.md | CONFIRMED principles |
| No deploy/push by agents | All specs | Cursor rules, CLAUDE.md, SECURITY.md | CONFIRMED |
| Skills/hooks/agents | Prompt pkg §3,§10–11 | `.claude/**` | Skeleton TODO |
| Deployment profiles | Bootstrap §6 | deployment-profiles.md | CONFIRMED principles |
| Provider interfaces | Bootstrap §5 | packages/provider-adapters READMEs | PROPOSED names |
| Core IDs on contracts | Bootstrap §2 | tenancy-model.md, api-event-contracts.md | Documented; schemas later |

## Constraints

- Spec originals unchanged
- No fabricated CONFIRMED tech choices

## Open decisions

See design §13 and k3s §12 rows still open.

## Source specification references

- All three `docs/specs/*_v1.md`

## Status

PROPOSED matrix

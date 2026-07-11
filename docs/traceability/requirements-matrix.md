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
| Prompt files (bootstrap/plan/execution/verification/handoff) | k3s §2 `prompts/`; Prompt pkg §4–9 | none | NOT SCAFFOLDED / OPEN DECISION |
| Eval suites (fixtures, trace-graders, policy-tests, regression) | k3s §2 `evals/`; Prompt pkg §12 | none | NOT SCAFFOLDED / OPEN DECISION |
| `forgectl` CLI | k3s §1–2 | none | NOT SCAFFOLDED / OPEN DECISION |
| Multi-host skills (portable/codex/cursor, ponytail-pinned) | k3s §2 `skills/`; Prompt pkg §10 | `.claude/skills/` only (Claude host) | PARTIAL / OPEN DECISION |
| Multi-host hooks (common/codex/cursor) | k3s §2 `hooks/`; Prompt pkg §11 | `.claude/hooks/` only (Claude host) | PARTIAL / OPEN DECISION |
| Contract asyncapi/compatibility subdivisions | k3s §2 `contracts/` | `packages/contracts/` README only | NOT SCAFFOLDED / OPEN DECISION |
| GRS / B-tier remediation·credit owner | Algorithm §0 B계층, §13-7 | none — spec 자체가 미결 선언 | OPEN DECISION (§13 의사결정 주체·일정 확정 선행) |
| 관측 셀·treatment/control 등록 원장 owner | Algorithm §3.7-1; k3s Gate C | 어느 서비스 Owned data에도 없음 | OPEN DECISION (권고: experiment-attribution 소유 + audit-ledger hash 앵커링) |
| UsageRecord / per-tenant metering owner | k3s §9.2 Cost 대시보드 | none (billing OUT OF SCOPE) | OPEN DECISION |
| prompts/·evals/·forgectl/ 보류 승인 주체 | k3s §2 | requirements-matrix 행만 (보류 승인자 미명기) | OPEN DECISION — 사용자 승인 필요 (boot B4) |
| 계약 단위 vs 배포 단위 해석 | k3s §0 vs §11 Gate A | ADR-0002 | accepted (2026-07-12; 모듈 통합만 보류) |
| 승인 전이 권위 경로 | k3s §4.3 | ADR-0003 | accepted (2026-07-12) |
| envelope 필수 ID vs Strategy Card 익명성 | k3s §4.1 vs Algorithm §8.4 | ADR-0006 | accepted 안 A (2026-07-12) — 충돌 해소, events 구현 가능 |

## Constraints

- Spec originals unchanged
- No fabricated CONFIRMED tech choices

## Open decisions

See design §13 and k3s §12 rows still open.

## Source specification references

- All three `docs/specs/*_v1.md`

## Status

PROPOSED matrix

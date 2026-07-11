# AGENTS.md — Role catalog (bootstrap)

## Purpose

Host-portable agent role definitions for SAENA FORGE development and B-department runs.  
Full `.claude/agents/*.md` bodies are **deferred** — this file is the role contract sketch.

## Scope

Lead/Orchestrator, Architecture, AEO Science, Platform, Backend, Security, Test/QA, Integration.

## Current decision

PROPOSED role boundaries for harness development. Runtime MAS roles (Discovery/Planner/etc.) remain in design §9.

---

### Lead / Orchestrator

| Field | Value |
|---|---|
| 책임 | Plan Mode 조율, 승인 게이트, 병렬화 결정, 완료 매트릭스 |
| 허용 도구 범위 | read; plan artifacts; coordination commands |
| 수정 가능 경로 | `docs/architecture/**` (draft); run manifests under `.saena/` when present |
| 수정 금지 경로 | `packages/contracts/**`, `deploy/**`, customer source without contract |
| 입력 | design specs; run-context; Action Contract status |
| 산출물 | PLAN.md; coordination status; READY/BLOCKED decisions |
| 완료 조건 | 모든 critical gate 소유자 확인; evidence bundle 완전 |

### Architecture

| Field | Value |
|---|---|
| 책임 | 서비스 경계, 계약, 배포 프로파일 정합성 |
| 허용 도구 범위 | read; ADR drafts |
| 수정 가능 경로 | `docs/architecture/**`, `docs/decisions/**` |
| 수정 금지 경로 | 임의 서비스 구현; 계약 silent break |
| 입력 | specs; service-catalog; ADRs |
| 산출물 | ADR; boundary reviews |
| 완료 조건 | OPEN DECISION 명시; CONFIRMED와 구분 |

### AEO Science

| Field | Value |
|---|---|
| 책임 | Query Cluster, claim/evidence, citation vs absorption, experiment design |
| 허용 도구 범위 | read; analysis notebooks/docs (future) |
| 수정 가능 경로 | `docs/` AEO sections; `services/intelligence/**` docs; `services/optimization/**` docs; `services/experimentation/**` docs |
| 수정 금지 경로 | scoring 구현 silent change; provider adapter internals without Architecture |
| 입력 | observation cells; evidence ledger; research refs |
| 산출물 | hypothesis portfolios; measurement plans |
| 완료 조건 | evidence IDs; no unsupported claims; ChatGPT-only scope |

### Platform

| Field | Value |
|---|---|
| 책임 | k3s, Helm, Temporal, event bus, observability, runner isolation |
| 허용 도구 범위 | read; deploy docs (no live cluster apply in agent scope) |
| 수정 가능 경로 | `deploy/**` docs/skeleton; `workflows/**` skeleton; `services/platform/**` docs |
| 수정 금지 경로 | live `kubectl apply`; production secrets |
| 입력 | k3s ops spec; profiles |
| 산출물 | chart skeleton; runbooks; SLO docs |
| 완료 조건 | profile separation; default-deny documented |

### Backend

| Field | Value |
|---|---|
| 책임 | 서비스 API 구현 (향후), gRPC/REST, data ownership |
| 허용 도구 범위 | scoped write after Action Contract / ADR |
| 수정 가능 경로 | assigned `services/<area>/<service>/**` only |
| 수정 금지 경로 | other services' DB; `packages/contracts` without owner approval |
| 입력 | contracts; schemas; events |
| 산출물 | service code (future); contract tests |
| 완료 조건 | contract tests green; tenant IDs present |

### Security

| Field | Value |
|---|---|
| 책임 | policy gate, secrets, NetworkPolicy, prompt-injection, red-team |
| 허용 도구 범위 | read + security tools; write deny for product code unless scoped |
| 수정 가능 경로 | `docs/architecture/security-model.md`; `deploy/policies/**` skeleton; security tests docs |
| 수정 금지 경로 | 정책 완화; long-lived credential injection |
| 입력 | threat model; failure-mode fixtures |
| 산출물 | deny evidence; security critic reports |
| 완료 조건 | critical policy violation 0; secrets 0 in artifacts |

### Test / QA

| Field | Value |
|---|---|
| 책임 | contract/integration/e2e/security/perf strategy; gate matrix |
| 허용 도구 범위 | test runners (future); read diffs |
| 수정 가능 경로 | `tests/**`; quality gate docs |
| 수정 금지 경로 | deleting tests to pass; product logic without Backend |
| 입력 | quality-gates; patch units |
| 산출물 | gate results; regression suites |
| 완료 조건 | required gates executed; skip 금지 |

### Integration

| Field | Value |
|---|---|
| 책임 | provider adapters, host adapters (Claude/Codex/Cursor), event wiring |
| 허용 도구 범위 | read; adapter skeleton docs |
| 수정 가능 경로 | `packages/provider-adapters/**`; `packages/source-connectors/**`; host adapter docs |
| 수정 금지 경로 | activating Google/Gemini in v1; cross-tenant wiring |
| 입력 | engine-adapter contracts; feature flags |
| 산출물 | adapter boundaries; compatibility notes |
| 완료 조건 | chatgpt-search primary; others PLANNED only |

## Constraints

- Cursor vs Claude Code scope: see `.cursor/rules/`
- Protected paths require human approval

## Open decisions

- Exact subagent file set under `.claude/agents/` — TODO
- Tool lease matrix per role — TODO (hooks)

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §9
- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §5–8

## Status

PROPOSED role catalog / agent markdown bodies NOT IMPLEMENTED

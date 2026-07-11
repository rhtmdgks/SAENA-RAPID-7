# SAENA RAPID-7 + FORGE

ChatGPT Search 중심 AEO 최적화 엔진(RAPID-7)과 고객 소스코드 안전 패치 Harness(FORGE).

## Purpose

SAENA Labs 내부 B부서가 사용하는 k3s-based package 저장소.  
고객 웹사이트 **소스코드 분석·수정·패치/PR 산출**까지. 배포·CMS 게시·git push·자동 merge는 **OUT OF SCOPE**.

## Scope

| In scope | Out of scope |
|---|---|
| Plan → human approval → MAS patch → quality gates → handoff | Production deployment |
| ChatGPT Search observation/optimization (v1) | Google AI Overviews / AI Mode / Gemini activation (v1) |
| Evidence-backed source changes | Unsupported claims, fake reviews, link schemes |
| Internal k3s + future SaaS profiles | Customer-owned cluster as product (v1) |

## Current decision

- **CONFIRMED:** 24 microservices named in design specs; ChatGPT Search only for v1 engine activation
- **CONFIRMED:** human-approval-gated Action Contract before write
- **CONFIRMED (2026-07-12):** architecture 계층 최종화 — 24 logical capabilities = 8 Deployment + 10 worker-hosted module (2 workers) + 5 Job + 1 merged infra; 계약 포맷 = JSON Schema/OpenAPI/AsyncAPI (proto 이연); ADR-0001~0008. 상세: `docs/architecture/`, `docs/decisions/`
- **PROPOSED:** monorepo layout (directory skeleton)
- **OPEN DECISION:** 언어 스택 / design §13 7건 / `docs/architecture/` 잔여 OPEN

## Constraints

1. API-first / contract-first / event-contract-first
2. tenant-aware (`tenant_id`, `workspace_id`, `project_id`, `site_id`, `run_id`, `actor_id`)
3. evidence-first; immutable audit trail
4. no deployment by execution agents
5. customer source isolation (per-run workspace)
6. algorithm ≠ infrastructure ≠ provider adapter

## Repository layout (bootstrap)

- `apps/` — operator console, API gateway
- `services/` — 24 microservices by domain area
- `packages/` — shared contracts, schemas, adapters
- `workflows/` — Temporal definitions/activities (skeleton)
- `events/` — event catalog/schemas
- `deploy/` — Helm charts & deployment profiles
- `docs/` — specs (immutable originals), architecture, ADRs
- `.claude/`, `.cursor/` — agent harness scaffolding

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md`
- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md`
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md`

## Status

**Bootstrap scaffolding** — NOT IMPLEMENTED application code.

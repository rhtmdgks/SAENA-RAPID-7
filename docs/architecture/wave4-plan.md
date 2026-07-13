# Wave 4 (Intelligence) — authority, scope, DAG

Branch: `wave4-intelligence` (from `main` = `a1f1b08`, merged Wave 3 PR #4).
This is a Wave-4 WORK document (not `docs/specs/**` — those stay immutable).

## Authority (extracted, verbatim-cited)

- **Wave 4 scope** (implementation-waves.md §W4): "intelligence-worker P0 4 모듈 +
  chatgpt-observer(browser pool) + QEEG read-only projection + ClickHouse·vector
  도입 (시간 파티션+ORDER BY 규칙 — ADR-0007 rev.2) + 실험 등록 원장(hash 앵커링)."
- **ClickHouse** — CONFIRMED (ADR-0007; data-ownership.md:26). append-only;
  **time partition + ORDER BY (tenant_id, …) prefix**; tenant-level partition
  FORBIDDEN (high-cardinality). Owning tables: chatgpt-observer(ROL),
  citation-intelligence, experiment-attribution, observation stack. Raw
  snapshots/artifacts are content-addressed refs (artifact-registry single
  gateway); ClickHouse stores metadata/hash/ref, not raw customer content.
- **Vector** — data-ownership.md:28 lists **"Qdrant/pgvector"** (both), tenant
  partition, owned by demand-graph/claim-evidence/entity-resolution;
  ADR-0007 rev.2: "Vector = 제품별 collection·namespace 결정". No single-tech
  ADR ruling. → treated as PORT-abstracted; the concrete CI-integration backend
  is an implementation choice from the two authorized options (see w4-07 note),
  NOT a normative product decision.
- **Discriminator vs partition** (ADR-0007 rev.2): tenant_id discriminator on
  every tenant-scoped record/event (SystemContext exempt); per-store physical
  partition (Postgres schema+RLS 2nd, ClickHouse time-partition+ORDER BY(tenant_id,…),
  Redis/objstore prefix, vector per-product collection/namespace).
- **QEEG** — physical projection owned by **claim-evidence-service**
  (ADR-0007:28); read-only CQRS (data-ownership rules); event-replay rebuildable.
- **Envelope** (ADR-0013/0006): 3-context (Tenant/System/Aggregate); required
  fields event_id/tenant_id/run_id/schema_version/producer/occurred_at/trace_id/
  idempotency_key; no PII in payloads; tenant_id discriminator mandatory.
- **Compat** (ADR-0012): closed=major-only, event open=additive-minor; single
  harness tests/contract/**; registry+schema lockstep; positive+negative fixtures;
  generated-model parity. Single owner = Contracts Steward.
- **Experiment ledger** — registration ONLY (baseline/treatment/control or
  matched cluster, metric defs, query cluster, locale, browser policy, repeat
  count, asset hash, code/version hash, created_by/approved_by, timestamp,
  canonical hash, previous-hash anchor). Reuse `saena_domain.audit` hash chain +
  canonicalization (no new hashing rule). **NO outcome/DiD/causal/lift** (Wave 5).
- **Engine** — chatgpt-search ONLY; Google AIO/AI-Mode/Gemini deny (schema +
  guard). **Forbidden in W4**: absorption-analysis(P1), digital-twin,
  portfolio-optimizer, strategy-skill-bank, causal/lift/DiD/KPI-weight, outcome
  analysis, strategy-card-eligible, production customer observation, prod deploy.

## Existing vs new events

- Reuse (exist): `site.inventory.completed.v1`, `repo.intaken.v1`,
  envelope/context/error/identifier common contracts.
- NEW (Contracts Steward, w4-10): `demand.graph.versioned.v1`,
  `entity.graph.versioned.v1`, `claim.evidence.versioned.v1`,
  `citation.normalized.v1`, `observation.captured.v1`,
  `experiment.registered.v1`, `experiment.anchored.v1` (+ any domain payload
  contracts: demand-cluster, entity, claim, evidence, citation-record,
  platform-observation, experiment-registration). Confirm against registry;
  reuse where semantics suffice.

## Entry / Exit

- Entry: W3 PR #4 merged to main (a1f1b08), post-merge verify+smoke green,
  wave4-intelligence branched from main. ✓
- Exit: see prompt §13 (P0 4 modules, browser-pool real path, QEEG replay,
  ClickHouse+vector real integration, experiment ledger tamper detection,
  contracts compat, tenant-isolation adversarial, composite E2E, rollback,
  deploy static validation, 16 existing + new named checks, determinism 3/2,
  all critics PASS, exit report).

## Patch-unit DAG (exclusive paths)

Stage 0
- w4-00: this authority/DAG doc (docs/architecture/wave4-*.md) — Lead.
- w4-01: package/service scaffold + import boundaries (root config = Integrator).

Stage 1 (parallel; no path overlap)
- w4-02 demand-graph → services/intelligence/demand-graph-service/**, tests/unit/svc_demand_graph/**
- w4-03 entity-resolution → services/intelligence/entity-resolution-service/**, tests/unit/svc_entity_resolution/**
- w4-04 claim-evidence → services/intelligence/claim-evidence-service/** (excl QEEG proj = w4-11), tests/unit/svc_claim_evidence/**
- w4-05 citation-intelligence → services/intelligence/citation-intelligence-service/**, tests/unit/svc_citation_intelligence/**
- w4-06 ClickHouse adapter/migrations → packages/analytics-clickhouse/** (new pkg), tests/unit/analytics_clickhouse/**, tests/integration/clickhouse/**
- w4-07 vector adapter/index lifecycle → packages/vector-store/** (new pkg, port + one CI backend), tests/unit/vector_store/**, tests/integration/vector/**
- w4-08 browser-pool observer → services/acquisition/chatgpt-observer-service/**, tests/unit/svc_chatgpt_observer/**, tests/integration/browser_observer/**
- w4-09 experiment ledger → packages/domain/src/saena_domain/experiment/** + services/experimentation/experiment-attribution-service/**, tests/unit/{domain_experiment,svc_experiment_attribution}/**
- w4-10 contracts/events/registry (single owner) → packages/contracts/**, packages/schemas/** (codegen), tests/contract/**
- QEEG belongs to claim-evidence but split to w4-11 to keep w4-04 core deterministic.

Stage 2
- w4-11 QEEG read-only projection/replay → packages/domain/src/saena_domain/qeeg/** + claim-evidence projection module, tests/**
- w4-12 intelligence-worker orchestration/service boundary → services/intelligence/README + worker wiring, .importlinter
- w4-13 observation→artifact→ClickHouse→citation integration → tests/integration/intelligence_pipeline/**
- w4-14 Helm/deploy (extend saena-forge) → deploy/charts/saena-forge/** (intelligence-worker/browser-pool/ClickHouse/vector workloads, SA/RBAC/NetworkPolicy/probes/PDB), tests/unit/deploy/**
- w4-15 observability registry/dashboards → packages/observability/**, deploy dashboards
- w4-16 security/privacy/adversarial suite → tests/security/**

Stage 3
- w4-17 composite synthetic E2E → tests/e2e/intelligence/**, tests/integration/intelligence_e2e/**
- w4-18 failure/rollback/rebuild/idempotency → tests/security + tests/integration/**
- w4-19 CI named checks + coverage + exit report + PR body → .github/workflows + justfile + docs/architecture/wave4-*
- w4-20 final integration critics (Security/Data-Isolation + Architecture/Evidence-Integrity)

## Named CI checks (justfile SSOT, ADR-0018)
`intelligence-e2e`, `storage-integration`, `browser-observer`, `qeeg-replay`,
`experiment-integrity` (final names confirmed at w4-19).

## OPEN decisions (repo authority confirms these are undecided — isolate, do NOT invent)

Cited from storage-authority extraction (2026-07-13):
1. Vector store product (Qdrant vs pgvector) — Algorithm spec §398 lists both; no ADR pick. → port + pgvector CI backend (implementation choice), Qdrant equally authorized behind the port. NOT blocked.
2. Embedding model/version/dimension spec — OPEN; P0 principle "local embedding/reranking only" (k3s §258). → deterministic TestEmbedder, no external API; provider recorded production-only. NOT blocked.
3. ClickHouse per-table TTL/retention — OPEN (service-owner scope). → leave TTL unset, record production-only. NOT blocked.
4. PII vs immutable audit (legal) — OPEN (ADR-0007 line 59). → gates Wave 5 output; W4 ledger carries NO PII, reuses audit chain. NOT a W4 blocker.
5. Graph store product (Neo4j vs Postgres) — OPEN, P1. → out of W4 scope (QEEG uses read-only projection, not a new graph DB).
6. Managed vs in-cluster data services — OPEN → deploy references external connections (SecretRef), not an inline product decision; production-only.

None of these BLOCK a W4 unit — each is isolated behind a port / synthetic / production-only note.

## Isolation candidates (block only the dependent unit)
- Vector tech (Qdrant vs pgvector): dual-authorized → port + one CI backend
  (pgvector: reuses existing Postgres testcontainer, lowest CI/infra risk), Qdrant
  documented as equally-authorized alternative behind the same port. NOT blocked.
- Retention/TTL, PII scope, embedding provider, live-observation, external
  credential method: OPEN per prompt → use deterministic/synthetic (test embedder,
  fixture browser, no external creds); record any live value as production-only.

# Wave 4 (Intelligence) — exit report

Branch: `wave4-intelligence` (from `main` = `a1f1b08`, merged Wave 3 PR #4).
Authority + DAG: `docs/architecture/wave4-plan.md`. This is a Wave-4 WORK
document, not `docs/specs/**`.

## Status

Stage 0–3 COMPLETE and integrated to `wave4-intelligence` (all 20 DAG units).
Final integration critics (w4-20) + the Wave-4→main PR are the only remaining
steps. **No Wave-4→main merge is performed here — that stays a human decision.**

## Delivered units (integrated, `just verify` green at each merge)

| Unit | Deliverable | Evidence |
|------|-------------|----------|
| w4-00 | Authority/scope/DAG doc | `docs/architecture/wave4-plan.md` |
| w4-06 | ClickHouse analytical store + migrations | `packages/analytics-clickhouse`; append-only, `PARTITION BY toYYYYMM(occurred_at)` + `ORDER BY (tenant_id, occurred_at, id)`; real-container integration lane |
| w4-07 | Vector store (port + pgvector backend) | `packages/vector-store`; `VectorStore` Protocol, tenant-filter enforced, cross-tenant NN-leakage blocked; pgvector real-container lane |
| w4-09 | Experiment **registration** ledger | `saena_domain.experiment`; canonical hash + previous-hash anchor (reuses `saena_domain.audit`), append-only, structural no-outcome guard |
| w4-10 | 12 new contracts + codegen | registry 26→38 (5 closed domain records + 7 open events); tenant/3-context envelope at channel-overlay; all engine-scoped |
| w4-02 | Demand Graph module | `saena-demand-graph`; deterministic canonical query clusters + provenance → `demand.graph.versioned.v1` |
| w4-03 | Entity Resolution module | `saena-entity-resolution`; alias canonicalization, competitor-not-owned (no bypass), cross-tenant fail-closed → `entity.graph.versioned.v1` |
| w4-04 | Claim–Evidence ledger | `saena-claim-evidence`; fail-closed publishability (unsupported/stale/blocked → BLOCKED), append-only hash chain → `claim.evidence.versioned.v1` |
| w4-05 | Citation Intelligence | `saena-citation-intelligence`; deterministic URL normalization + ownership (rule + calibrated prior), engine closed-enum → `citation.normalized.v1` |
| w4-08 | Browser-pool observer | extends `saena_chatgpt_observer`; read-only pool, artifact single-gateway (ref+hash, no inline raw), `observation.captured.v1`; real Playwright driver integration-lane only |
| w4-11 | QEEG read-only projection/replay | `saena_domain.qeeg` (generic fold) + `saena_claim_evidence.qeeg_projection`; rebuildable-by-replay, idempotent, read-only, publishability copied verbatim |
| w4-12 | Intelligence-worker service boundary | `services/intelligence/README.md`; boundary enforced by `services-are-independent` import-linter contract |
| w4-14 | Helm/deploy | `deploy/charts/saena-forge`; intelligence-worker + browser-pool-coordinator workloads, SecretRef-only, observer SA read-only (no write RBAC, no git cred, token automount off) |
| w4-15 | Observability registry/dashboards | `packages/observability.intelligence`; naming-validated metrics/spans, redaction denylist + V-AGG rule, no raw content in labels |
| w4-16 | Security/privacy/adversarial suite | `tests/security/test_intel_*`; 6 guards, each mutation-verified to fail iff its guard is removed |

## Verification evidence

- Blocking unit lane (`just test` = `-m "not integration"`): **4113 passed**, 38
  skipped, 0 failed.
- `just verify` green at every integration commit: 11 import-linter contracts
  KEPT (incl. `services-are-independent` covering all 4 intelligence services +
  observer; `*-below-services` for clickhouse/vector), coverage ratchet held at
  the 99% baseline, ruff + mypy + JSON-Schema + AsyncAPI + OpenAPI validation
  clean.
- 22 commits `a1f1b08..HEAD`.

## Wave-4 scope adherence (forbidden-scope NOT touched)

- Engine = **chatgpt-search ONLY**. Google AIO/AI-Mode/Gemini rejected at the
  shared `guard_engine_id` / `EngineFactory` boundary and per-service; pinned by
  `tests/security/test_intel_engine_scope.py` (mutation-verified).
- Experiment feature is **registration ONLY** — NO outcome/DiD/causal/lift/
  KPI-weight. The open-class event payloads (ADR-0012) cannot schema-reject a
  stray `lift`/`outcome` field, so that boundary is documented as the
  `outcome-field-gap` **policy-gate obligation** (contract gap fixture +
  `failure_mode_matrix.json` `missing_owner_note`), not silently treated as
  enforced. NOT implemented: absorption-analysis (P1), digital-twin,
  portfolio-optimizer, strategy-skill-bank, strategy-card, outcome analysis.
- No production observation / deploy / release / tag. Helm is chart definition
  only.

## Data-isolation & security invariants (tested)

- `tenant_id` discriminator on every tenant-scoped record/event; cross-tenant
  access fail-closed and **non-leaking** (tenant-B-vs-real and
  tenant-B-vs-nonexistent raise structurally identical errors) — entity/demand/
  claim-evidence stores + artifact gateway + QEEG projection.
- Raw customer content never inlined: observations carry only `raw_object_ref` +
  `artifact_hash`; a planted raw-content marker is proven absent from record,
  event payload, audit trail, and a simulated log line.
- No PII/secret in event payloads or observability labels.
- ClickHouse tenant-level partition FORBIDDEN (time-partition + ORDER BY tenant
  prefix); vector per-product namespace.

## OPEN decisions (isolated, not invented — per wave4-plan §"OPEN decisions")

Vector product (Qdrant vs pgvector) → port + pgvector CI backend. Embedding
model/version → deterministic TestEmbedder, provider production-only. ClickHouse
TTL/retention → unset, production-only (values comment). PII-vs-audit legal →
gates Wave 5; W4 ledger carries no PII. Graph store (Neo4j vs Postgres) → out of
W4 (QEEG is read-only projection). Managed vs in-cluster data services → external
SecretRef, production-only. None blocked a W4 unit.

## Stage 3 (integration/E2E depth + CI wiring) — COMPLETE

- w4-13 observation→artifact→ClickHouse→citation pipeline: 15 tests, verified
  LIVE against a real ClickHouse container (`tests/integration/intelligence_pipeline/**`).
- w4-17 composite synthetic E2E: 31 tests (26 synthetic + 5 real-ClickHouse),
  whole-chain determinism + tenant isolation + registration-only experiment leg
  (`tests/e2e/intelligence/**`, `tests/integration/intelligence_e2e/**`).
- w4-18 failure/rollback/rebuild/idempotency: 35 tests (incl. real-Postgres) —
  idempotent replay, QEEG rebuild, fail-closed rollback (no partial state),
  tenant isolation under failure, ledger tamper detection
  (`tests/integration/intelligence_failure/**`).
- w4-19 named CI checks (justfile SSOT + `.github/workflows/ci.yml` jobs):
  `browser-observer`, `storage-integration`, `qeeg-replay`,
  `experiment-integrity`, `intelligence-e2e` — all pass locally.

## w4-20 final verification

Two independent critics (Security/Data-Isolation, Architecture/Evidence-
Integrity) were dispatched. Per the honest-critic convention established in
Wave 3, they idle-signalled without delivering a bus verdict, so the Lead
performed the adversarial verification directly (documented, not claimed as a
critic PASS):

**Security / Data-Isolation → PASS.** Engine scope is a closed enum
(`ALLOWED_ENGINE_IDS = {"chatgpt-search"}`) + the central
`saena_domain.execution.guard_engine_id`; no bypass/override/default engine path
exists (the only "default" references are comments asserting none is hardcoded).
Tenant isolation: 96 tenant guards, every store getter takes `tenant_id` as its
first parameter, cross-tenant access fail-closes and does not leak existence
(13 mutation-verified tests in `test_intel_tenant_isolation.py`). Raw-content
discipline is defended in depth: observation payloads carry only
`raw_object_ref`+`artifact_hash`; `saena_analytics_clickhouse.guard.guard_row_fields`
is invoked at all three ClickHouse insert sites (`rows.py`) and fail-closed
rejects any raw_content/raw_html/screenshot/response_body/secret column;
observability redaction denylists claim_text/excerpt/source_uri/query_text. No
live-observation path — fixture browser only, real Playwright driver guarded +
coverage-omitted.

**Architecture / Evidence-Integrity → PASS.** No outcome/DiD/causal/lift logic
exists in the intelligence stack — every such token in `src/**` is a negative
assertion of the boundary, not a computation; `FORBIDDEN_OUTCOME_TOKENS` is a
real structural guard. Both the experiment ledger and the claim-evidence ledger
import `saena_domain.audit.canonical.canonical_json`/`sha256_hex` verbatim (no
new hashing rule); tamper (content/forged-hash/forged-previous-hash) is detected
at genesis/middle/prior entries (w4-18). QEEG projection is read-only
(write-method-monkeypatch test) and deterministically rebuildable by replay;
publishability is copied verbatim from the fail-closed write-model. Determinism
(identical graph_version/content_hash across runs) is proven by w4-13/w4-17. All
11 import-linter boundary contracts KEPT; registry 26→38 with codegen↔schema
parity.

## Remaining

- Wave-4 → main PR (CI green). **Merge is a human decision — no auto-merge.**

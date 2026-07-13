# Wave 4 remediation report

Branch: `wave4-remediation` (from `main` = `a8de390` = PR #5 merged). Closes four
concurrency/integrity/privacy defects the original Wave-4 CI did not catch. No
`docs/specs/**` / accepted-ADR-status / release changes.

## Verification method (honest)

Each unit was built reproducer-first by an independent implementer in its own
git worktree and verified LIVE against real containers (Postgres/pgvector,
ClickHouse). No separate critic agent delivered a message-bus verdict, so — per
the remediation brief's explicit fallback — the **Lead** ran the same
adversarial verification directly against real containers and records it as
"Lead verification" (not a critic PASS). For r4-04 the Lead additionally acted
as the independent critic: it found two MUST-FIX defects in round 1, returned
them to the author, and re-verified the round-2 fix (see below).

## Findings

### r4-01 — pgvector concurrent upsert (integration SHA `d561265`)
- **Root cause**: `SELECT … WHERE superseded = FALSE … FOR UPDATE` locks nothing
  on the first upsert of a new `(tenant_id, collection, record_id)` key (no row
  exists to lock); no DB constraint enforced active-row singularity. Concurrent
  first-upserts could create multiple active rows.
- **Invariant**: at most one `superseded = FALSE` row per key; concurrent
  first-upserts converge to exactly one active row with intact history.
- **Old-code reproducer**: `tests/integration/vector/test_pgvector_concurrency.py::test_old_impl_first_upsert_race_produces_duplicate_active_rows` — 20 concurrent first-upserts through a faithful pre-fix reconstruction (unconstrained schema) yields `active_count > 1`.
- **Fix**: Postgres transaction advisory lock (`pg_advisory_xact_lock`) keyed on
  server-side `hashtextextended(tenant_id|collection|record_id)` (stable
  cross-process, NOT Python `hash()`, NOT a process-local lock) acquired on the
  KEY before the active-row read; a partial `UNIQUE INDEX … WHERE superseded =
  FALSE` DB backstop; same-connection active-row read.
- **Adversarial evidence** (real pgvector:pg16): 20 same-snapshot & 20
  different-snapshot concurrent → 1 active row; racing a pre-existing active row
  → 1; partial index rejects a forced duplicate INSERT; different keys not
  globally serialized. 23 integration tests, 3× deterministic; 63 unit.
- **Lead verification**: PASS — re-ran the live suite (23 passed).

### r4-02 — ClickHouse distributed idempotency (integration SHA `c1c7f47`)
- **Root cause**: `_exists_idempotency_key()` then `insert_rows()` = check-then-
  insert race; MergeTree has no UNIQUE constraint, so concurrent writers both
  pass the check and both insert.
- **Invariant**: for every table + `(tenant_id, idempotency_key)`, no matter how
  many independent writer processes call `append_*`, at most one row is
  **logically** observable via `get_*` — backed by a **window-bounded physical**
  guarantee (disclosed, not claimed unconditional).
- **Old-code reproducer**: `tests/integration/clickhouse/test_idempotency_distributed.py::TestOldImplementationRaces::test_old_check_then_insert_shape_duplicates_under_concurrent_writers` — 20 concurrent writers of the old shape → 10 physical duplicate rows.
- **Fix**: ClickHouse server-side atomic `insert_deduplication_token`
  (deterministic, `\x1f`-delimited, tenant-namespaced token) +
  `non_replicated_deduplication_window = 1000` on every owned table (default is
  0/disabled — confirmed live, not assumed). An adapter-internal `dedup_witness`
  column lets `append_*` report `True`/`False` honestly (never gating the
  insert). No `saena_domain` import (package is a standalone leaf); reuses the
  ON-CONFLICT *principle*, not the code.
- **Physical vs logical (disclosed)**: physical dedup holds within the 1000-block
  window (no non-replicated `_seconds` variant in this CH version); outside it a
  sufficiently delayed duplicate is not guaranteed. `append_*`'s bool return is
  documented as "was I the first-observed writer," not a relational-unique claim.
- **Adversarial evidence** (real clickhouse:24.8): 20 concurrent → exactly 1
  physical row (tally True=1/False=19); all 3 tables; cross-tenant non-collision;
  crash/retry/resend. 19 integration (stable 5×) + 109 unit.
- **Lead verification**: PASS — re-ran the live distributed-idempotency suite (8 passed).

### r4-03 — experiment ledger chain integrity (integration SHA `dd82859`)
- **Root cause**: `compute_experiment_hash` excluded `previous_hash`, and that
  value was both stored as `canonical_hash` and checked by `verify_ledger` — so
  reorder + relink + reuse-of-unchanged-canonical_hash (forgery-free) passed
  verify.
- **Old-code reproducer**: `tests/unit/domain_experiment/test_ledger.py::test_old_vulnerability_reorder_and_relink_would_have_passed_verify` — the OLD code returns `(True, None)` on a reorder+relink (independently recorded before the fix).
- **Fix**: split identities — `compute_content_fingerprint` (content-only, for
  idempotent-replay compare) vs `compute_experiment_hash` (chain-entry hash =
  `canonical_json({previous_hash, content_fingerprint})`, stored as
  `canonical_hash` + checked by `verify_ledger`). Commits chain position. Reuses
  `saena_domain.audit.canonical` verbatim (no new hashing rule). Additive
  `content_fingerprint` field; explicit format boundary documented (pre-r4-03
  entries fail the new verify).
- **Adversarial evidence**: 12 adversarial tests (middle-content tamper, forged
  canonical/previous hash, reorder ±relink, middle-deletion+relink, cross-ledger
  splice+relink, genesis change) all fail-closed; intact replay deterministic;
  byte-identical registration idempotent. 53 tests, 3× deterministic.
- **Lead verification**: PASS — independently confirmed reorder+relink rejected
  on the fixed code.

### r4-04 — query privacy boundary (integration SHA `21a8fbd`)
- **Root cause**: `ObservationRow.query_text` persisted the raw customer query
  (≤2000 chars) verbatim in `observations.query_text String`; the shape-only
  guard never caught an ordinary sentence with an email/phone/customer-id.
- **Old-code reproducer**: `tests/integration/clickhouse/test_query_privacy_boundary.py` plants a query with an email + phone + API token + customer id and asserts the planted string is absent from the physical row / logical `ObservationRow` / every `repr()`.
- **Independent-critic MUST-FIX loop (round 1 → round 2)**: round-1 stored
  `query_ref = query://<tenant>/sha256(raw_query)` — the Lead-as-critic found (a)
  it is brute-forceable for low-entropy queries (raw dropped, not stored access-
  controlled) and (b) the hash excluded tenant → cross-tenant correlation.
  Returned to author; round-2 fix verified.
- **Fix**: `query_text` column removed (same-commit format boundary). Replaced
  with `query_ref` (required): **keyed HMAC-SHA256** with `tenant_id` INSIDE the
  HMAC input (`{tenant}\x1f{raw_query}`), key from runtime SecretRef (env
  `SAENA_ANALYTICS_QUERY_SIGNING_KEY`), FAIL-CLOSED with no keyless path — not
  brute-forceable without the key, and the same query under different tenants
  yields different refs. Optional `query_digest` (default `None`, unused by the
  pipeline): keyed HMAC correlation primitive, deliberately tenant-global for
  "seen-before" correlation, documented as correlation-not-isolation.
- **Persisted fields after the fix** (`observations`): `tenant_id, id,
  idempotency_key, occurred_at, ingested_at, engine_id, run_id, query_ref,
  query_digest (nullable), citation_refs, raw_object_ref, dedup_witness` — **no
  raw query text**.
- **Adversarial evidence** (real ClickHouse): planted PII absent from physical +
  logical row + every repr; keyed-ref brute-force resistance; same-query-two-
  tenants → different ref; SecretRef-missing fail-closed; normal chatgpt-search
  E2E success; forbidden engine still rejected. 156 unit + 94 integration.
- **Lead verification**: PASS — confirmed keyed/tenant-scoped derivation + re-ran
  the live privacy suite (20 + 5 passed).

## r4-05 — cross-unit regression + named gates (integration SHA `20464dd`)
- Full integration lane **301 passed** + e2e **32 passed** (all 4 fixes coexist,
  real containers).
- Determinism: unit lane **4216 passed ×3 identical**; integration
  (vector+clickhouse) **62 passed ×2 identical**.
- New justfile SSOT named gates + ci.yml jobs (jobs call the recipes; no test
  command duplicated in YAML): `vector-concurrency`, `analytics-idempotency`,
  `experiment-chain-adversarial`, `intelligence-privacy`.

## Compatibility / migration impact
- r4-03: `ExperimentRegistration` gains `content_fingerprint` (additive);
  pre-r4-03 ledger entries (canonical_hash without previous_hash) fail the new
  `verify_ledger` — explicit format boundary, no prior production data.
- r4-04: ClickHouse `observations` column set changed (`query_text` →
  `query_ref` + nullable `query_digest`) — same-commit format boundary, no prior
  production data. `query_text` does not appear in any published JSON-Schema
  contract, so no versioned-contract / registry / codegen change was required.
- No published contract was broken; `saena_domain` / `saena_analytics_clickhouse`
  standalone-leaf import boundary intact (11/11 import-linter contracts KEPT).

## Residual / OPEN (not packaged as PASS)
- r4-02 physical exactly-once is **window-bounded** (1000 blocks), not
  unconditional — a duplicate delayed beyond the window is caught logically
  (query-time), not physically. Disclosed in the store docstring + API return
  semantics.
- r4-04 `query_digest` is an optional, keyed, deliberately tenant-global
  correlation primitive (unused by the pipeline). A signing-key holder can
  correlate the same query across tenants via the digest; without the key it is
  opaque. This is a documented design choice, not an uncontrolled leak.
- `SAENA_ANALYTICS_QUERY_SIGNING_KEY` is supplied at runtime via SecretRef only;
  wiring the real key into a production deployment is a production-only action
  (no key value is committed).

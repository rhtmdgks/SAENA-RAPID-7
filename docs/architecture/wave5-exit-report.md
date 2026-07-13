# Wave 5 (Measurement·B-Layer) — exit report

Branch: `wave5-measurement` (from `main` = `156568c`, W4 PR #5 + remediation PR #6).
Plan/DAG: `docs/architecture/wave5-plan.md` (commit `6e40907`).
Engine scope: ChatGPT Search ONLY. Date: 2026-07-14.

## Status

**PARTIAL PASS** — the full W5 measurement·B-layer *mechanism* (21 of 24 seed
units) is delivered, independently critic-verified, and `just verify`-green.
Three units are residual: **w5-19** (E2E harness delivered, test cases cut
short by an external account rate-limit), **w5-20** (failure-mode suite
partial + one seam finding), **w5-21** (Helm — BLOCKED on human protected-path
approval). Production operation (real GRS thresholds, live ChatGPT observation,
real customer deployment, live cluster) is BLOCKED(human/production-only) and
is NOT claimed PASS anywhere. No unsupported external-lift claim is made.

## Delivered units (integrated on wave5-measurement)

| Unit | Feature | Integrating SHA | Critic verdict |
|---|---|---|---|
| w5-00 | plan/authority/DAG | `6e40907` | — |
| w5-01 | measurement package skeleton | `0d1b6b6` | — |
| w5-02 | measurement contracts/events (registry 38→43, channel #17) | `af24af8` | PASS |
| w5-03 | deployment confirmation + trusted 7-day clock | `138cbd5` | PASS (correctness + security) |
| w5-04 | experiment binding — immutability + contamination | `8f1053d` | PASS (correctness + security) |
| w5-05 | deterministic per-signal DiD engine | `8a9ce0c` | PASS (stats + adversarial) |
| w5-06 | outcome-layer + ≥2-independent-layer B-gate | `bcf37a7` | FAIL→rework→re-verify PASS |
| w5-07 | GRS policy — signed bundle, fail-closed | `4165a60` | FAIL×2→rework→re-verify PASS |
| w5-08 | evidence-bundle manifest (tamper-evident) | `7545c19` | PASS (correctness + security) |
| w5-09 | persistence ports + idempotency + conformance | `3b77f2b` | PASS |
| w5-10 | Postgres persistence (real container lane) | `d833cb0` | PASS (docker lane ran) |
| w5-11 | ClickHouse outcome projection (real container) | `4e9c116` | PASS (docker lane ran) |
| w5-12 | experiment-attribution service boundary | `d82c3bd`,`1a7ff63` | PASS (security) |
| w5-13 | fail-closed measurement pipeline | `d82c3bd`,`78d3aee` | PASS (composition) |
| w5-14 | durable 7-day Temporal workflow (time-skipping) | `3e3dd78`,`e7ff5fc` | PASS (durable-workflow) |
| w5-15 | observation scheduling/rate-policy (fixture-only) | `9f93d5d` | FAIL→rework→re-verify PASS |
| w5-16 | skill-bank B-verified-only intake boundary | `18c2412` | PASS (fail-closed-privacy) |
| w5-17 | observability registry (spans/metrics/attrs) | `a76ea31`,`bfa558a` | PASS (conventions) |
| w5-18 | privacy/tenant + cross-module adversarial suite | `774eb24` | PASS (test-vacuity 9/9) |
| w5-22 | measurement named CI gates (justfile + ci.yml) | `80530a8` | Lead |

Integration fixes caught by the Integrator that the isolated worktrees missed:
`d28a263` (w5-13 mypy narrowing — real types only visible post-integration),
`f3a7802` (w5-12 `factories.py` basename collision with `svc_quality_eval`,
full-lane only). Both are genuine defects the parallel-worktree model surfaces
only at merge.

## Exit-matrix mapping (wave5-plan.md E1–E12)

| # | Condition | Proven by | Status |
|---|---|---|---|
| E1 | Treatment/control registration immutable + measurement-time mutation/contamination rejected | `tests/unit/domain_measurement_binding` (49) | PASS |
| E2 | `deployment.confirmed.v1` sole clock start; identity/hash/target/confirmer/server-timestamp/idempotency/replay/backdate/cross-tenant validated | `tests/unit/domain_measurement_clock` (73) + `tests/integration/measurement_workflow` (9, time-skipping RAN) | PASS |
| E3 | DiD deterministic, recovers synthetic effect, never passes zero-effect, separates common trend; FP/FN fixtures | `tests/unit/domain_measurement_did` (41), 3× determinism | PASS |
| E4 | B-gate ≥2 independent layers (duplicate-basis once); 1-layer≠PASS; insufficient/contaminated/late⇒UNDETERMINED+reason | `tests/unit/domain_measurement_bgate` (73), maximum-matching order-invariant, NaN/inf forge-PASS dead | PASS |
| E5 | Evidence bundle complete + tamper/reorder/splice-evident; no raw content/secrets | `tests/unit/domain_measurement_evidence` (99) | PASS |
| E6 | GRS signed bundle; missing/unsigned⇒fail-closed; TEST-ONLY fixture; production values BLOCKED | `tests/unit/domain_measurement_grs` (66) | PASS (mechanism) / BLOCKED(human §13-7 for production values) |
| E7 | skill-bank consumes ONLY B-verified outcomes (fail-closed) | `tests/unit/svc_strategy_skill_bank` (40) | PASS |
| E8 | Tenant/privacy/idempotency/replay invariants | `tests/unit/domain_measurement_ports` (105) + `tests/security/measurement_privacy_tenant.py` (10) | PASS |
| E9 | Real-container (Postgres/ClickHouse) + Temporal time-skipping integration; mock-only E2E forbidden | `tests/integration/measurement_pg` (39, real PG), `clickhouse_outcome` (14, real CH), `measurement_workflow` (9, time-skipping) | PASS |
| E10 | All existing + new W5 named gates green; `just verify` 3× | `just verify` green; 8 W5 named gates green | PASS (see verification) |
| E11 | Independent critic requirement satisfied or Lead fallback disclosed | 21 independent critic runs (3 FAIL→rework→re-verify); w5-18 single-critic+Lead disclosed; w5-22 Lead | PASS (disclosed) |
| E12 | No forbidden P1/Future activation; no deploy; no unsupported lift claim | scope audit below | PASS |

## Clock / DiD / B-gate / GRS / evidence — key guarantees proven

- **Clock**: window constructible ONLY from an Accepted confirmation
  (token-guarded); anchor = server_received_at (payload `confirmed_at` is a
  claim, never anchors — a real mutation to use it flips a pinned integration
  test); Day-2-late ⇒ UNDETERMINED(deployment_late), timer never armed;
  duplicate idempotent, conflicting fail-closed; DST/tz-proof by instant
  arithmetic; crash-at-day-3.5 replay continues to the ORIGINAL end.
- **DiD**: `net_of_control_lift = (postT−baseT)−(postC−baseC)`; Fraction-exact,
  ROUND_HALF_EVEN 10dp, permutation-invariant byte-identical; F-9 fraud fixture
  (raw +5/+5 → 0) parity; insufficiency taxonomy never guesses.
- **B-gate**: PASS requires ≥2 independent layers via MAXIMUM bipartite matching
  (order-invariant); NaN/inf forged-PASS provably dead (allow_inf_nan=False +
  defensive isfinite + negation-form guard); raw_view from real deltas; 3-way
  verdict never collapsed; no weights parameter.
- **GRS**: signed bundle, strict `is True` verifier, unsigned-production refused,
  serializability validated at construction (no evaluate-time crash), missing
  threshold ⇒ DENY naming key (zero hardcoded thresholds, tokenize-enforced);
  production values BLOCKED(human).
- **Evidence bundle**: position-committing hash chain (reuses
  `saena_domain.audit.canonical`, no new hashing rule); tamper/reorder/splice
  localized; NFKC+casefold raw-content/secret guard; missingness reported
  honestly, never silently completed.

## Critic MUST-FIX found and fixed (adversarial verification worked)

1. **w5-06 NaN/inf forged PASS** (FAIL): a non-finite `net_of_control_lift`
   passed both `<= 0` and `> 0` comparisons → silent PASS with confidence 1.0.
   Fixed: `allow_inf_nan=False` + defensive isfinite + negation-form guard.
   Re-verify: 11/2/2 mutation kills, provably dead.
2. **w5-07 truthy-verifier fail-open** (FAIL): `if not verify()` treated a
   truthy non-bool ("false"/1/object) as trusted. Fixed: strict `is not True`.
3. **w5-07 bundle_hash TypeError crash** (FAIL, round 2): lazy `bundle_hash`
   property crashed `evaluate_grs_eligibility` on non-serializable values.
   Fixed at root: validate serializability at construction, cache the digest.
4. **w5-15 rolling-24h rate cap fail-open** (FAIL): slots packed at window
   start could exceed max_per_day in any sliding 24h window. Fixed: uniform
   stride `max(min_gap, ceil(86400/max_per_day))`, proven by construction +
   10-test mutation kill.

Independent re-verification (same-lens critic) confirmed each fix dead before
integration. Numerous non-blocking should-fixes applied (documented in commits).

## Real-container / time-skipping evidence

- **Postgres** `postgres:16-alpine` testcontainer RAN: w5-10 39 integration
  tests (port conformance + concurrent-writer race + rollback + SF-4 tamper).
- **ClickHouse** `clickhouse-server:24.8-alpine` testcontainer RAN: w5-11 14
  integration tests (append/get, logical-dedup-beyond-window, cross-tenant).
- **Temporal** time-skipping WorkflowEnvironment RAN: w5-14 9 integration tests
  3× identical (7-day skip, crash-at-3.5 replay, duplicate/conflict/abort/
  Day-2-late, DST, pause-holds-decision-past-end) — zero wall-clock sleep.
- `measurement-privacy` named gate exercises the real PG + CH containers in one
  lane (10.6s locally).

## Scope adherence (E12)

FORBIDDEN, verified absent: conversion/attribution as 7-day metric; KPI-weight
auto-optimization (B-gate takes no weights parameter); Google AIO/AI-Mode/Gemini
(engine_id closed `["chatgpt-search"]`, schema-rejected); absorption-analysis
P1 model / digital-twin / portfolio / bandit / survival (absorption is a data
enum value only); strategy-card auto-approval/global-sharing (skill-bank =
fail-closed intake boundary only, no approve/promote/share/learn surface —
structural test); production deploy/push; raw customer content/secrets in
events/logs/audit (guard + w5-18 leakage sweep). W4 outcome-field-gap: closed
via the w5-12 boundary publisher-side policy-gate obligation (fail-closed PASS
gate), not silently.

## Residual / OPEN / production-only

- **w5-19 (E2E)** — RESIDUAL. A 779-line real-stack E2E harness
  (`tests/e2e/measurement/measurement_e2e_harness.py`) was delivered but the
  author was cut off by an external account rate-limit before writing the
  collectible `test_*` cases + `tests/integration/measurement_e2e/`. NOT
  integrated (harness-only). The `measurement-e2e` CI gate currently covers the
  boundary + pipeline + Temporal integration as an interim; the full
  multi-container composed E2E is a follow-up. Worktree preserved.
- **w5-20 (failure modes)** — RESIDUAL (partial). 15 of ~19 failure-mode
  integration tests written; the coverage-matrix gate referenced 2 unwritten
  files and the F-9 evaluator repoint (delegating `measurement_fraud.py` /
  `fm-09` to the integrated engine) was not finished. NOT integrated. The
  fail-closed / fraud / UNDETERMINED-never-PASS space IS covered by w5-18 (16
  cross-module tests, critic-verified 9/9 mutation kills) + w5-13 pipeline
  fail-closed branches. **Seam finding (real):** `run_measurement` does NOT
  convert a persistence-level `IdempotencyConflictError` (raised by
  `PgConfirmationStore` on a same-key/different-content conflicting
  confirmation) into a clean `UNDETERMINED(conflicting_confirmation)` outcome —
  the store exception propagates. Behaviour is SAFE (fail-closed, first-wins,
  never arbitrary, never PASS) but not graceful; a follow-up should wrap that
  write. Non-blocking (safety holds). Worktree preserved.
- **w5-21 (Helm/forgectl)** — BLOCKED(human). `deploy/**` protected-path
  approval was requested (consolidated decision H8) and not granted; no chart
  changes made.
- **GRS production thresholds + B-SLA remediation/credit** (§13-7) — BLOCKED(human).
- **ChatGPT observation methodology / account / rate-limit / ToS owner** (§13-1) — BLOCKED(human); dev uses approved-fixture adapter only.
- **PII-vs-audit legal** (W4 carry, H10) — bundle carries hashes/refs only, no raw content; legal sign-off pending.
- **Production-only**: live ChatGPT observation, real customer deploy + real
  `deployment.confirmed.v1`, live 7-day wall-clock, GRS underwriting/credit
  issuance, live ClickHouse/dashboards, cross-tenant card transfer, production
  key mgmt. None claimed PASS.
- **w5-11 SF (non-regression)**: `grs_policy_provenance` free-text shape is
  unvalidated beyond nonempty+≤512 + secret-guard — matches the w4-06 sibling
  convention (not a W5 regression); a stricter provenance-shape convention is a
  future decision.

## Human decisions (consolidated request shown 2026-07-14, unanswered)

H1 GRS threshold/SLA (§13-7), H2 observation methodology/ToS owner (§13-1),
H3 "independent layer" operational definition, H4 outcome_layer enum spelling,
H5 deployment.confirmed confirmer trust model, H6 7-day timer mechanism,
H7 reason-code vocabulary, H8 deploy/** (w5-21), H9 W5 exit-matrix sign-off,
H10 PII-vs-audit legal. Mechanism shapes were built per the directive's
pre-endorsed forms; production values remain BLOCKED.

## Rollback

Each unit is additive (new modules + additive contracts (minor) + additive
migrations + new named gates). Rollback = revert the unit's integrating
commit(s); envelope + the pre-W5 38 contracts + registration ledger untouched
(only additive registry entries). Helm untouched. No existing runtime path
altered — measurement services consume events only when wired.

## Verification

`uv run just verify` green at HEAD (`80530a8`): lint, typecheck (mypy 370
files), unit lane (5259+ passed), coverage ratchet held at 99% (temporalio +
workflow shell absorbed), boundaries (11 import contracts kept), contracts +
registry validate. 8 W5 named gates individually green. ci↔justfile parity
test green.

## DO NOT AUTO-MERGE

This branch is merge-ready for **human** review only. No admin/squash/rebase/
force; normal merge to main after human approval (CLAUDE.md principle 10). No
production deployment. No unsupported external-lift claim is made anywhere in
this wave.

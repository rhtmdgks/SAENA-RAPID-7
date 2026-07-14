# Wave 5 (Measurement·B-Layer) — exit report

Branch: `wave5-measurement` (from base `main` = `156568c`, W4 PR #5 + remediation
PR #6). Plan/DAG: `docs/architecture/wave5-plan.md` (commit `6e40907`).
**Current PR #7 head is the GitHub PR/branch tip — the authoritative moving
value; this document deliberately does NOT hardcode it (a commit cannot
reference its own future SHA).** Stable historical SHAs below name specific
integrating commits, not "the final HEAD". Engine scope: ChatGPT Search ONLY.
Date: 2026-07-14.

## Status

**PASS (code + static-deployment mechanism) — 24/24 seed units.** The Wave 5
Closure (commits `812c3a5`..`dab5e9a`) completed the three previously-residual
units and all associated defects, with independent adversarial critics on every
unit and honest Lead-fallback verification where spawned critics stalled.
Clean separation of what PASSes vs what remains human/production-gated:

- **Code / mechanism: PASS.** DiD activation, deployment.confirmed.v1 7-day
  clock, outcome_layer ≥2-independent-layer B-gate, evidence bundle, GRS
  fail-closed mechanism, B-verified-only skill-bank intake, real composed E2E,
  full failure-mode matrix, conflicting-confirmation seam. `just verify` green
  3× (deterministic); real Postgres 16 / ClickHouse 24.8 / Temporal
  time-skipping container lanes green 2×.
- **Static deployment package: PASS.** w5-21 saena-forge Helm wiring +
  validation (helm lint/template, kubeconform strict, forgectl preflight
  pos/neg, values.schema, deploy unit+integration tests) — human-authorized
  protected-path work (H8 grant recorded, commit `9099c1d`).
- **Live staging/production deployment: OPEN.** No live cluster in this
  environment; live install/rollback not run, not claimed.
- **Production GRS thresholds / SLA / credit, ChatGPT observation methodology
  + ToS, PII-vs-audit legal: BLOCKED(human).** Mechanism only; production
  values never invented, never claimed PASS.

No production deployment, no live customer observation, and **no unsupported
external-lift claim** is made anywhere.

### Wave 5 Closure — units, findings, remediation

| Closure unit | Scope | Integrating SHA(s) | Critic outcome |
|---|---|---|---|
| c5-03 | conflicting-confirmation seam fix | `812c3a5`,`9c10af7`,`4d177e8` | correctness PASS; security FAIL (multi-conflict `EvidenceHashMismatchError` crash) → fix → re-verify PASS |
| c5-04 | w5-21 Helm/deploy wiring (Lead-direct) | `9099c1d`,`d95a183`,`cb9a9d4` | PASS (deploy-security) + 2 should-fixes applied |
| c5-01 | w5-19 real composed E2E | `c7daad7`,`88ed805`,`1390c59`,`e0cedbf`,`bde828d` | FAIL×3 on the zero-collected guard (dead session-fixture → env-var contract; MF-1 dead-in-CI + MF-2 over-fire → env contract; RV-3 Docker-absent self-test skip → lazy fixtures) → re-verify PASS |
| c5-02 | w5-20 failure-mode matrix + F-9 repoint | `9a51d45`,`7077fd7` | PASS (failure-completeness); matrix 6-check gate proven to have teeth |
| c5-05 | wire real E2E/failure lanes into named gates | `c965a9e` | (the gaps c5-06 checked) |
| c5-06 | cross-unit adversarial audit | `75632e0`,`f9a6cca`,`dab5e9a` | audit-a FAIL (**real secret-leak**: hyphen-infix `sk-live-…` admitted into skill-bank PRODUCTION pool — 3 content guards missed the shape) → fix all 3 + regression → re-verify PASS; audit-b fail-closed/tenant/replay = Lead verification (spawned auditors stalled) |

**Key defect closed by the audit (would have shipped otherwise):** the shared
`_SECRET_SHAPED_PATTERNS` set (duplicated in intake.py / evidence.py /
analytics_clickhouse/guard.py) matched Stripe underscore (`sk_live_`) but NOT
the hyphen-infix convention (`sk-live-…`), so a real credential shape was
admitted verbatim into the strategy-skill-bank production candidate pool under
an innocuous field name — the sole enforcement point for the open-class
payload's "no raw content" invariant. Fixed across all three guards + ADMIT-path
regression tests (`75632e0`).

**Conflicting-confirmation seam (the w5-20 finding, now closed):**
`run_measurement` no longer lets a persistence `IdempotencyConflictError`
escape — it catches it by type and returns a deterministic
`UNDETERMINED(conflicting_confirmation)` with the first accepted record
unmutated; two unrelated same-tenant conflicts no longer collide (each conflict
records a run-distinguishing, fingerprint-only evidence entry).

### Honesty disclosures

- **c5-04 (w5-21 Helm) was Lead-authored**, not by an isolated write-agent: two
  spawned agents correctly declined the protected-path write on the strength of
  the then-stale `BLOCKED(human)` living-doc, refusing to trust a second-hand
  authorization claim. Resolution: the user's direct in-session H8 grant was
  recorded in `wave5-plan.md` (`9099c1d`), and the Lead — holding the
  first-party human authorization — did the deploy work directly. An
  independent critic (not the author) reviewed it: PASS.
- **c5-06 audit-b (fail-closed/tenant/replay) is Lead verification**, not an
  independent-critic PASS: the spawned auditor and its respawn stalled without
  delivering a verdict, so per CLAUDE.md principle 9 the Lead reran the
  adversarial probes directly (140 tests across the integrated container lanes
  + direct probes) and recorded the result honestly as Lead fallback
  (`/tmp` verdict `c5-06-audit-b-LEAD.json`; audit-a covered provider-scope +
  CI-vacuity + no-fake-mock independently). Every other unit has an independent
  critic that did not author it.

### Wave 5 Closure Final Remediation (required-gate fail-open)

A follow-up closure closed a **fail-open in both required integration gates**:
on a Docker-absent host the `measurement-e2e` and `measurement-failure-modes`
lanes collected their real-container scenarios, skipped ALL of them, and exited
0 — a green "0 passed, N skipped". The zero-collected guard caught only *zero
collected*, not *collected-but-all-skipped*. Fixed with a required-mode no-skip
guard (`pytest_sessionfinish`) in both conftests: when the lane's required env
var is set, any skipped required test — or zero passed — is a HARD FAILURE
(exit 6). The `just` recipes set the env var internally (SSOT), so a caller
cannot drop the required semantics. Proven: both recipes exit 6 on Docker-absent
via the real `just` invocation; both pass with real containers.

A same-lens re-verification (critic F) then closed two residual gaps: (1) a
**bypass** — a `-k` selection keeping only the container-free guard self-tests
left `pytest_sessionfinish`'s real-container set empty while `collection_finish`
stayed silent (dir items existed), so the lane could exit 0 having run zero real
scenarios; now an empty required-container selection is itself a HARD FAILURE
(exit 6). (2) **fail-safe arming** — arming is no longer exact `== "1"`; any
truthy value (`true`, `yes`, `" 1 "`) arms, so a typo can never silently
downgrade the required lane to the optional/honest-skip lane. Guard self-tests
updated to this contract (E2E 8, failure 4). Stale "w5-19/w5-20 residual"
comments in `justfile`/`ci.yml` were also corrected.

### Wave 5 Closure — Required-Scenario Completeness Remediation

The `pytest_sessionfinish` guards above (and the collected/skipped guards)
inspected only `session.items` — the tests pytest actually **selected** after
`-k` / `-m` / `--deselect` / single-node-path / `PYTEST_ADDOPTS` filtering. So a
caller who selected a **subset** left that selected set fully passing and the
gate went GREEN having run only a *fraction* of the required scenarios — a
partial-selection / deselection fail-open. Reproduced (Docker present, armed) at
the prior head: `-k <one test>` → exit 0 "1 passed, N deselected"; `--deselect`
of one required node → exit 0; a single node path → exit 0; dropping the whole
Temporal directory → exit 0 (composed passed, Temporal never ran);
`PYTEST_ADDOPTS=-k` → exit 0.

Closed with an authoritative **manifest SSOT + expected-vs-executed completeness
guard** (never a bare count — node-id SETS are compared, so a renamed test can't
substitute):

- **E2E** (`tests/integration/_measurement_e2e_completeness.py`): 28 required
  scenarios, each with a stable semantic id, its pytest node id, and its backend
  leg (postgres / clickhouse / temporal / composed). Wired into the **ancestor**
  `tests/integration/conftest.py` `pytest_sessionfinish`, so it fires for BOTH
  `measurement_e2e` + `measurement_workflow` and closes path-omission of either
  directory. Armed + any expected node not execute-and-PASS (deselected /
  uncollected / skipped / failed), or ZERO tests for any backend leg, or empty
  manifest → HARD FAILURE exit 6.
- **failure** (`tests/integration/measurement_failure/_failure_completeness.py`):
  31 required nodes (16 primary / 15 recovery), wired into the existing
  `measurement_failure/conftest.py` `pytest_sessionfinish`. Missing node, zero
  primary, or zero recovery → exit 6.
- **Invocation hardening**: both required `just` recipes prefix `PYTEST_ADDOPTS=''`
  on every pytest line (targeted per-command override — other recipes still honor
  a caller's `PYTEST_ADDOPTS`), so external `-k`/`-m`/`--deselect` injection
  cannot shrink the required set even before the guard runs. CI keeps calling
  `uv run just <recipe>` (SSOT) and adds an `if: always()` job-summary step
  (SHA + armed + recipe + injection-neutralized).
- **Drift meta-tests** (both lanes): assert the manifest node set equals the
  actual collectible set in BOTH directions — a renamed/removed real test, or a
  manifest-only entry, fails loudly, so the SSOT can never silently drift.

Manifest modules are TEST-SUPPORT only (under `tests/`, never imported by any
runtime/production package). Fail-safe arming + the terminalreporter None-guard
are preserved; `session.exitstatus = 6` is set before any reporter access.

### Wave 5 Closure — CI Evidence Integrity

**Remediation in progress; CI verification pending.** The CI job summaries no
longer emit a static success claim. Each required gate (`measurement-e2e`,
`measurement-failure-modes`) now writes a machine-generated evidence JSON
(schema `saena.gate-evidence/v1`) via the completeness guard, containing:
`required_mode_armed`; expected/selected/executed/passed/failed/skipped/
xfailed/xpassed/deselected counts; missing/unexpected/duplicate node ids;
per-leg (postgres/clickhouse/temporal/composed) executed/passed/witness;
`real_containers_proven`; and real-container **WITNESSES** — the Postgres,
ClickHouse, and Temporal image + container id, recorded by the fixtures
themselves only at the moment a real container actually starts (not asserted
by env var).

A fail-closed renderer (`tools/validation/render_gate_evidence.py`) verifies:
the evidence file exists; it matches the `saena.gate-evidence/v1` schema; it
is bound to **this** commit — `commit_sha` + `github_run_id` match the current
run, so stale evidence carried over from a prior run is rejected; and it
reports `completeness_passed` + `real_containers_proven` + `skipped=0` +
`missing=0`. If any of that fails, the CI step exits non-zero and the summary
reads NOT PROVEN / FAILED — never green by default. The summary is rendered
FROM this evidence; it is no longer a static echo. Evidence JSON files are
uploaded as CI artifacts (`if: always()`), so the raw witnesses survive the
run for independent audit.

This proves real-container execution from runtime witnesses captured by the
fixtures during execution — not from env-var declarations of intent. This is
a mechanism description only: the remediation has not yet been exercised on a
green CI run, and that verification is explicitly pending, not claimed here.

**Trust boundary (known limitation, future hardening).** The evidence is not
cryptographically signed: a hand-forged JSON carrying the *matching* commit_sha
+ github_run_id would render PROVEN. Exploiting this requires the ability to
inject a `run:` step that writes that file *between* the gate step and the
render step in the same job — a capability equal to editing `ci.yml` itself, so
it is outside this gate's threat model (a compromised workflow definition is a
different, higher-privilege problem). The real gate step always runs first and
atomically overwrites the evidence path with the true (pass-or-fail) state, so a
pre-planted file cannot survive a genuine run (independently verified). Signing
the evidence with a CI secret (HMAC) is recorded as future defense-in-depth; it
is deliberately not added here to avoid introducing a new managed secret.

### Original wave (pre-closure) status, superseded

The initial pass reached PARTIAL PASS (21/24) with w5-19/w5-20/w5-21 residual;
that state is fully superseded. All three units are integrated and verified.
Earlier per-commit verification claims against intermediate heads
(`80530a8`, `dab5e9a`, …) are historical; the authoritative current state is the
PR #7 head + its green CI, not any single hardcoded SHA.

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

- **w5-19 (E2E)** — CLOSED (c5-01). 28 required E2E scenarios +
  guard-mechanism tests in `tests/integration/measurement_e2e/` — real Postgres
  16 + ClickHouse 24.8 + Temporal time-skipping, no mock-only, no wall-clock
  sleep. A `SAENA_MEASUREMENT_E2E_REQUIRED=1` env-var contract arms a
  zero-collected hard-fail guard (a naming/import error collecting 0 exits
  non-0, never a silent pass) wired into the `measurement-e2e` named gate.
- **w5-20 (failure modes)** — CLOSED (c5-02). Full 31-node failure-mode matrix (16 primary / 15 recovery),
  every node existing + collectible + run-verified (6-check gate with teeth);
  F-9 repointed to the integrated `b_gate.decide_b_verdict` (thin shim, all
  importers green). 31 integration tests vs real Postgres. **Seam finding
  closed (c5-03):** `run_measurement` now catches the persistence
  `IdempotencyConflictError` by type and returns
  `UNDETERMINED(conflicting_confirmation)` (first record unmutated, two unrelated
  same-tenant conflicts no longer collide).
- **w5-21 (Helm/forgectl)** — CLOSED, static (c5-04). deploy/** authorized by the
  human (H8 grant, `9099c1d`). 2 measurement Deployments (experiment-attribution,
  strategy-skill-bank) via the generic `services.<key>` shape; digest-pinned +
  SecretRef-only + hardened + zero K8s API + no ClusterRole; GRS bundle a signed
  ExternalSecret with **no threshold values**; Google/Gemini fail schema +
  forgectl preflight. **Live install/rollback: OPEN** (no live cluster — not run,
  not claimed).
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

## Verification (Wave 5 Closure Final Remediation)

`uv run just verify` green 3× (deterministic): lint, typecheck, unit lane
(5297 passed), coverage ratchet held (99%), boundaries (11 import contracts
kept), contracts + registry validate. All 8 W5 named gates individually green;
ci↔justfile parity green.

**Required-gate fail-closed contract, proven end-to-end:**

| Gate | Docker present | Docker absent (required env armed) | Optional (flag unset) |
|---|---|---|---|
| `just measurement-e2e` | e2e 42 pass (28 real PG16 + CH24.8 + Temporal time-skipping rows + 14 guard proofs), skipped=0 | **exit 6 HARD FAILURE** (never green "0 passed, N skipped" **or a partial `-k`/`--deselect`/single-node/PYTEST_ADDOPTS selection**) | honest skip, exit 0 |
| `just measurement-failure-modes` | failure matrix 44 pass (31 real-PG rows + 13 guard proofs), skipped=0 | **exit 6 HARD FAILURE** (incl. any partial selection) | honest skip, exit 0 |

Real-container lanes green 2× each; guard self-tests: E2E 14 passed, failure 13
passed (incl. the container-free-only bypass, fail-safe-arming, and the
required-scenario **completeness** regressions — partial `-k`/`--deselect`/
single-node/`PYTEST_ADDOPTS` selection each hard-fail, plus the manifest drift
meta-test). No wall-clock sleep stabilizes Temporal (time-skipping only).
Failure-mode matrix: every declared node exists + is collectible + ran; primary
and recovery both run; skipped=0 and missing=0 in required mode.

## DO NOT AUTO-MERGE

This branch is merge-ready for **human** review only. No admin/squash/rebase/
force; normal merge to main after human approval (CLAUDE.md principle 10). No
production deployment. No unsupported external-lift claim is made anywhere in
this wave.

# Wave 5 (Measurement·B-Layer) → main

**DO NOT AUTO-MERGE.** Human review + normal merge only (no admin/squash/rebase/
force). No production deployment. No unsupported external-lift claim is made.

**Status: PASS (code + static-deployment mechanism), 24/24 seed units.** The
authoritative branch tip is the PR #7 head shown on GitHub (a moving value this
doc does not hardcode — a commit cannot reference its own future SHA). Live
cluster install/rollback is OPEN (not run); production GRS thresholds / ToS /
legal remain BLOCKED(human).
Full detail + honesty disclosures (Lead-direct w5-21 Helm under the recorded H8
grant; Lead-fallback verification for the fail-closed/tenant/replay audit lane)
in `docs/architecture/wave5-exit-report.md`.

## Authoritative scope

Wave 5 activates the *measurement / B-layer* half of the AEO engine on top of
Wave 4's registration-only experiment ledger (implementation-waves.md §W5;
Algorithm §3.7/§7.3; k3s Gate C; ADR-0002 rev.3/0003/0007/0013). Engine scope:
**ChatGPT Search only.** Five deliverables: DiD measurement activation,
`deployment.confirmed.v1` 7-day clock, `outcome_layer` ≥2-independent-layer
B-gate, evidence bundle, GRS policy mechanism (production values human-gated).

## Delivered (24/24 seed units, all critic-verified, `just verify` green 3×)

- **Contracts** (w5-02): `deployment.confirmed.v1` (channel #17), payloads for
  the envelope-only `experiment.outcome.observed.v1` / `strategy.card.eligible.v1`,
  domain `experiment-outcome`/`evidence-bundle-manifest`; registry 38→43,
  engine_id closed `["chatgpt-search"]`, envelope untouched.
- **Domain core** (w5-03..09): trusted deployment confirmation + 7-day clock
  (server-time anchor, Day-2 rule), immutability/contamination binding,
  deterministic DiD, ≥2-independent-layer B-gate (maximum bipartite matching),
  GRS fail-closed signed-bundle policy, tamper-evident evidence bundle,
  persistence ports + conformance suite.
- **Adapters/services/workflow** (w5-10..17): real-Postgres persistence,
  real-ClickHouse outcome projection, experiment-attribution service boundary
  (tenant-scoped lookup, fail-closed publisher), fail-closed pipeline, durable
  7-day Temporal workflow (time-skipping), fixture-only observation scheduling,
  B-verified-only skill-bank intake, observability registry.
- **Assurance** (w5-18, w5-22): cross-module privacy/tenant + adversarial
  suite (9/9 mutation kills); 8 named CI gates + the collection-gap fix so the
  non-`test_*` security files actually run in CI.

## Exact SHAs

Base main: `156568c`. Per-unit integration commits are in
`docs/architecture/wave5-exit-report.md` (one table row each). The current
branch tip is the PR #7 head shown on GitHub — the authoritative moving value;
this doc does not hardcode it (a commit cannot reference its own future SHA).

## Required-gate fail-closed contract (Wave 5 Closure)

Both required integration gates hard-fail (exit 6) — never a green "0 passed,
N skipped" — when Docker/ClickHouse/Temporal is absent, any required test is
skipped, or zero collected, with the required env var armed by the recipe (SSOT).
Docker-present: `measurement-e2e` 39 pass / `measurement-failure-modes` 41 pass,
real containers, skipped=0. Optional/local (flag unset): honest skip. Arming is
fail-safe (any truthy value arms; a typo never downgrades to the optional lane).

**Required-scenario completeness** (final closure): the guards no longer trust
only the SELECTED set. An authoritative manifest SSOT (28 E2E scenarios across
postgres/clickhouse/temporal/composed legs; 31 failure nodes, 16 primary /
15 recovery) is compared against what actually execute-and-PASSED, so a partial
`-k`/`-m`/`--deselect`/single-node/`PYTEST_ADDOPTS` selection — or dropping a
whole backend leg — hard-fails (exit 6) instead of going green on a fraction of
the required scenarios. The recipes additionally clear `PYTEST_ADDOPTS` per
command so external selection injection cannot shrink the set. Drift meta-tests
keep each manifest in lock-step with the real suite (both directions).

## Wave 5 Closure — CI Evidence Integrity

**In progress; CI verification pending — not yet claimed green.** The prior
`if: always()` job-summary step echoed a static success line; it never proved
anything about the run that produced it. Remediation replaces the echo with a
fail-closed evidence chain: each required gate (`measurement-e2e`,
`measurement-failure-modes`) now writes a machine-generated evidence JSON
(schema `saena.gate-evidence/v1`) via the completeness guard, recording
`required_mode_armed`, expected/selected/executed/passed/failed/skipped/
xfailed/xpassed/deselected counts, missing/unexpected/duplicate node ids,
per-leg executed/passed/witness, `real_containers_proven`, and real-container
**witnesses** — Postgres/ClickHouse/Temporal image + container id, recorded by
the fixtures only when a real container actually starts. A fail-closed
renderer (`tools/validation/render_gate_evidence.py`) verifies the evidence
file exists, matches the schema, and is bound to **this** `commit_sha` +
`github_run_id` (stale evidence from a prior run is rejected), then reports
`completeness_passed` + `real_containers_proven` + `skipped=0` + `missing=0` —
otherwise the CI step exits non-zero (NOT PROVEN / FAILED). The job summary
renders FROM this evidence; it is never a static echo again. Evidence files
are uploaded as CI artifacts (`if: always()`). This proves real-container
execution from runtime witnesses recorded during the run, not from env vars
asserting intent. Mechanism only — this has not yet run green on CI; that
verification is pending.

## Evidence

- Unit lane 5297 tests; per-unit 100% (or ≥99%) module coverage; global
  coverage ratchet held at 99%.
- **Real containers**: Postgres `16-alpine` (39 tests RAN), ClickHouse
  `24.8-alpine` (14 RAN), Temporal time-skipping (9 RAN, 3× identical, zero
  wall-clock sleep). No mock-only E2E for the container legs.
- 8 W5 named gates green individually; ci↔justfile parity test green.

## Critic findings + fixes

Adversarial verification caught and killed 4 blocking defects before
integration (each re-verified dead by a same-lens critic): NaN/inf forged-PASS
(w5-06), truthy-verifier fail-open + bundle_hash crash (w5-07), rolling-24h
rate-cap fail-open (w5-15). Integrator additionally caught 2 defects the
isolated worktrees missed (w5-13 mypy narrowing; w5-12 factory basename
collision, full-lane only).

## Security / privacy / tenant

Envelope-only tenant authority (ADR-0014, payload duplication rejected);
tenant-scoped registration lookup neutralizes the w5-03 cross-tenant oracle at
the service boundary; verify_manifest at every deserialization/publish trust
boundary; raw-content/secret guards (NFKC-normalized) across evidence + rows +
skill-bank; no raw customer query/content/secret in any event/log/audit
payload (w5-18 leakage sweep).

## Closed in Wave 5 Closure / open / production-only

The initial pass reached PARTIAL PASS (21/24) with w5-19/w5-20/w5-21 residual;
the Closure round CLOSED all three (see `wave5-exit-report.md` c5-01…c5-04):

- **w5-19 E2E** — CLOSED (c5-01). Real composed E2E integrated: real Postgres 16
  + ClickHouse 24.8 + Temporal time-skipping, driving the actual
  `run_measurement` composition; run by the required `measurement-e2e` gate
  (39 pass, skipped=0, Docker-present; exit 6 Docker-absent).
- **w5-20 failure-modes** — CLOSED (c5-02). Full failure-mode matrix integrated
  (`measurement-failure-modes` gate: 41 pass, skipped=0). The conflicting-
  confirmation seam is CLOSED (c5-03): `run_measurement` now catches the
  persistence `IdempotencyConflictError` and emits `UNDETERMINED
  (CONFLICTING_CONFIRMATION)` — never PASS — instead of propagating the raw
  exception; the SAFE store-level first-content-wins behaviour is preserved.
- **w5-21 Helm** — CLOSED, STATIC only (c5-04). saena-forge Helm wiring +
  forgectl preflight + kubeconform pass offline; `deploy/**` authorized under the
  recorded H8 grant (Lead-direct authorship, disclosed). **Live cluster
  install/rollback is NOT run — OPEN.**
- **Production**: GRS thresholds/SLA (§13-7), ChatGPT observation methodology/
  ToS (§13-1), PII-vs-audit legal, live cluster/observation/deploy — all
  BLOCKED(human/production-only), none claimed PASS.
- 10 human decisions (H1–H10) surfaced; mechanism shapes built per the
  directive's pre-endorsed forms.

## Rollback

Fully additive; revert integrating commit(s) per unit. Envelope + pre-W5 38
contracts + registration ledger untouched. No existing runtime path altered.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

# Wave 5 (Measurement·B-Layer) → main

**DO NOT AUTO-MERGE.** Human review + normal merge only (no admin/squash/rebase/
force). No production deployment. No unsupported external-lift claim is made.

**Status: PASS (code + static-deployment mechanism), 24/24 seed units.** Final
branch HEAD `dab5e9a` (Wave 5 Closure complete). Live cluster install/rollback
is OPEN (not run); production GRS thresholds / ToS / legal remain BLOCKED(human).
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

## Delivered (21/24 seed units, all critic-verified, `just verify` green)

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

Integration commits per unit are in `docs/architecture/wave5-exit-report.md`
(one table row each). Branch HEAD: `80530a8` (+ w5-23 docs commit).

## Evidence

- Unit lane 5259+ tests; per-unit 100% (or ≥99%) module coverage; global
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

## Residual / open / production-only

- **w5-19 E2E** — harness delivered, test cases cut short by an external
  account rate-limit; NOT integrated (interim coverage via measurement-e2e gate).
- **w5-20 failure-modes** — partial (15 tests) + one real seam finding
  (`run_measurement` propagates a persistence `IdempotencyConflictError` on
  conflicting confirmation rather than emitting a clean UNDETERMINED — SAFE but
  not graceful; follow-up). Fail-closed/fraud/UNDETERMINED space is covered by
  w5-18 + pipeline.
- **w5-21 Helm** — BLOCKED(human): `deploy/**` approval not granted.
- **Production**: GRS thresholds/SLA (§13-7), ChatGPT observation methodology/
  ToS (§13-1), PII-vs-audit legal, live cluster/observation/deploy — all
  BLOCKED(human/production-only), none claimed PASS.
- 10 human decisions (H1–H10) surfaced; mechanism shapes built per the
  directive's pre-endorsed forms.

## Rollback

Fully additive; revert integrating commit(s) per unit. Envelope + pre-W5 38
contracts + registration ledger untouched. No existing runtime path altered.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

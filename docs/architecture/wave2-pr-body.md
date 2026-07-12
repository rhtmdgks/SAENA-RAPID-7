# Wave 2 PR body (prepared, NOT submitted — human action required)

> This file is the drafted `gh pr create --body` content for the Wave 2
> (`wave2-runtime` → `main`) pull request. Per w2-20 task scope: **prepare
> only, do not push/create/merge.** A human must review this content,
> initiate the actual PR, and merge it.

---

## Summary

Wave 2 (W2A 승인 코어 / W2B 오케스트레이션·아티팩트 / W2C 버스·관측·패키징)
delivers the SAENA FORGE approval-core, orchestration, and event-bus runtime
on top of the Wave 1 contract set: 5 foundation/platform services
(tenant-control, policy-gate, plan-contract, audit-ledger, forge-console-api),
Temporal-backed execution orchestration with a real signal-path E2E,
PostgreSQL persistence adapters, Redpanda outbox drain + consumer
idempotency, and a static `forgectl preflight` k3s gate CLI. All W2A/W2B/W2C
exit conditions named in `docs/architecture/implementation-waves.md` are
PASS at the code level, backed by directly-executed test evidence (see
`docs/architecture/wave2-exit-report.md`). Deploy/infra-level items (Helm
chart, dashboards, production cluster) are honestly BLOCKED(human) — see
that same report.

This PR (`w2-20`) additionally: (1) root-causes and fixes a flaky
integration test discovered under full-suite load by splitting test
execution into a deterministic unit+contract lane (`just verify`) and a
separate real-container/test-server integration lane (`just
test-integration`); (2) registers `tools/forgectl` as a proper `uv`
workspace member so mypy/coverage/import-boundary gates cover it; (3)
produces the Wave 2 exit-condition evidence report and this PR body.

## Unit list (21 implementation units + this exit unit, all on
`wave2-runtime`)

| Unit | Scope | Integrating SHA |
|---|---|---|
| w2-00-bootstrap | Wave 2 workspace bootstrap | `774a00c` |
| w2-01-identity | tenant/actor/namespace identity runtime | `208f33d` |
| w2-02-envelope | event envelope factory + validation runtime | `7e91f59` |
| w2-03-privacy | k-anonymity runtime gate | `3935c54` |
| w2-04-audit | append-only audit hash chain + forbidden-data guard | `a2ec793` |
| w2-05-policy | approval state machine + H-3/H-7 + RBAC | `a7f7293` |
| w2-06-observability | tenant-safe logging + trace + redaction runtime | `a0688a4` |
| w2-07-persistence | persistence ports + in-memory adapters + outbox | `fb92704` |
| w2-08-tenant-control | tenant-control-service (W2A) | `e90c0a5` |
| w2-09-policy-gate | default-deny engine + fail-closed | `ff02e0e` (+ `37968d8` critic fix) |
| w2-10-audit-ledger | append-only ledger API + lineage RBAC | `f2cb096` |
| w2-11-plan-contract | ADR-0003 approval path, fail-closed gate | `013b5c2` |
| w2-12-forge-console | forge-console-api — v1 edge | `59a7f4d` |
| w2-13-postgres | PostgreSQL adapters for persistence ports | `474ea0f` (+ `9ab7940` critic fix) |
| w2-14-approval-e2e | W2A approval exit evidence (E2E suite) | `17d5599` |
| w2-15-orchestrator | Temporal signal path (ADR-0003, W2B) | `3cc2d16` (+ `e2dfee3` critic fix) |
| w2-16-artifact-registry | blob single gateway + immutable manifests | `6a343e4` |
| w2-17-engine-gateway | closed-enum engine boundary, v1 chatgpt-search only | `3616f79` |
| w2-18-outbox-bus | outbox drain → Redpanda publish, W2C | `b9c0347` (+ `ec34a0c` critic fix) |
| w2-19-forgectl | preflight CLI — static config gate | `153fc24` |
| w2-21-gate-contract | plan-contract↔policy-gate HTTP contract fix | `2d3baba` (+ `37968d8`/`153fc24`-adjacent fixes) |
| **w2-20-wave2-exit** (this unit) | deterministic gate split, forgectl workspace, exit report + PR prep | *(pending commit — see FINAL REPORT)* |

## Exit-condition evidence

Full W2A/W2B/W2C exit-condition-by-exit-condition mapping (test
`path::name`, integrating SHA, PASS/BLOCKED verdict):
**`docs/architecture/wave2-exit-report.md`**.

Summary: every code-level exit condition PASSES with directly-executed test
evidence. No claim in that report is made without a citation.

## BLOCKED(human) — deploy/infra, not code

- `saena-forge` Helm chart (`deploy/**` protected path, no chart authored)
- 6 observability dashboards (no OTel collector/dashboard backend deployed)
- Real Temporal persistence DB / MinIO / Redpanda **production** deployment
  (this Wave proves wiring against real ephemeral test instances only —
  169/169 integration-lane tests green)
- Helm rollback drills (depend on the chart + a live cluster, neither exists)

Full rationale for each: `docs/architecture/wave2-exit-report.md`
"BLOCKED(human, out of Wave-2-code-scope)".

## Known non-blocking follow-ups (not fixed in Wave 2, tracked honestly)

- policy-gate `env -S` / `sh -c` builtin residual (default-deny under
  shipped rules — a false-positive/precision gap, not a fail-open bypass)
- plan-contract `QUORUM_PENDING` audit-reason mapping standing in for a
  not-yet-added `GATE_DENIED` code in `saena_domain.policy`
- partition-key convention — still OPEN DECISION (`docs/architecture/
  resilience.md`, ADR-0007 rev.2)
- `GateCheckRequest`'s 6 policy-gate-required fields are typed OPTIONAL on
  the port (populated in practice, not type-enforced)

Full detail: `docs/architecture/wave2-exit-report.md` "Known non-blocking
follow-ups".

## Flaky-gate fix + test totals

Root cause: `tests/integration/**` (real Temporal time-skipping test
server, `postgres:16-alpine`/`redpandadata/redpanda` testcontainers)
contended with ~2,100 concurrent deterministic tests when run in one
`pytest` invocation — process-scheduling noise, not a code defect (each
affected test passed 3/3+ in isolation).

Fix: `tests/integration/conftest.py` (new) auto-marks every test under
`tests/integration/**` `pytest.mark.integration`; `just test` (blocking,
inside `just verify`) now runs `-m "not integration"`; a new `just
test-integration` recipe runs `-m integration` separately/serially. Full
detail (including the honest, documented coverage-ratchet adjustment for
`persistence/postgres/adapters.py`, which is 100% integration-lane-covered
and has no meaningful unit-lane coverage of its own):
`docs/architecture/testing-strategy.md` "Two-lane test execution".

**Test totals** (measured w2-20, `wave2-runtime` + all 21 units + this
unit's own changes):

- Unit + contract lane (`just verify` → `just test`, blocking):
  **2,137 passed, 26 skipped (N-1 compat, first-release vacuous), 169
  deselected (integration)** — verified deterministic across 5 consecutive
  runs, identical counts every run.
- Integration lane (`just test-integration`, separate/serial): **169
  passed, 2,163 deselected** — verified across 2 consecutive runs.
- `just verify` full gate chain (lint, typecheck, test, coverage-gates,
  boundaries, contracts-validate, registry-validate): green, 3+ consecutive
  runs.

## Config changes in this PR (w2-20)

- `tests/integration/conftest.py` — new, universal `integration` marker
  auto-tagging (path-scoped `pytest_collection_modifyitems`).
- `justfile` — `test` recipe now `-m "not integration"`; new
  `test-integration` recipe.
- root `pyproject.toml` — `integration` marker registered
  (`[tool.pytest.ini_options]`); `tools/forgectl` added to
  `[tool.uv.workspace]` members, `[tool.uv.sources]`, dev-group deps,
  `[tool.mypy]` files, `[tool.coverage.run]` source; documented `omit` entry
  for `persistence/postgres/adapters.py` (integration-lane-only coverage,
  not silently weakening the ratchet).
- `.importlinter` — `saena_forgectl` added to `root_packages` with two new
  boundary contracts (leaf: may only import `saena_schemas`; nothing may
  import it back).
- `uv.lock` — regenerated for the new workspace member.
- `tools/forgectl/pyproject.toml`, `tools/forgectl/README.md` — packaging
  note updated to reflect real workspace membership (was previously
  documented as deliberately excluded, w2-19).
- `tests/unit/domain_events/test_uuid7.py` — one pre-existing, unrelated
  timing-race test (`test_generate_uuid7_ordering_is_monotonic_within_same_
  millisecond`) fixed to test the internal counter directly instead of
  relying on real wall-clock same-millisecond collisions across 50 calls —
  discovered as a SECOND source of `just verify` nondeterminism during this
  unit's own verification runs, fixed in the same spirit as the named
  flaky-gate task (deterministic `just verify` was the hard requirement).
- `docs/architecture/testing-strategy.md`, `docs/architecture/
  implementation-waves.md` — two-lane test note + Wave 2 exit status
  recorded.
- `docs/architecture/wave2-exit-report.md`, `docs/architecture/
  wave2-pr-body.md` — new (this deliverable).

## Footer

**No main merge. No git push. No tag. No release. This PR has NOT been
created or submitted — a human must review this drafted body, initiate the
actual `gh pr create`, and perform the merge.** Per CLAUDE.md principle 10
(배포·push·merge 금지) and the w2-20 task's own explicit scope boundary.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

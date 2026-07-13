# Wave 3 PR body

> `gh pr create --body` content for the Wave 3 (`wave3-execution` → `main`)
> pull request. Merge is human-gated (no auto-merge, no tag, no release, no
> production deploy).

## Summary

Wave 3 (Execution) delivers the FORGE execution runtime on top of the Wave 2
approval/orchestration/bus core: the **5 execution Jobs** (repository-intake,
agent-runner, quality-eval, chatgpt-observer, site-discovery) on a shared
`saena_domain.execution` layer, the **5-hook FORGE runtime ladder**, **ADR-0004
ServiceAccount 3-separation** in the chart, a **14-step composite E2E**
(application-chain synthetic E2E + separate real-container integration proofs on
real Temporal/Redpanda/Postgres — not a single all-real transaction), the
**9-mode failure matrix** (k3s §10, now **9/9** — F-5 resolved by a dedicated
skill-bundle content-integrity verifier, w3-12) with a **rollback verification
gate**, and a **deterministic 9-axis eval suite** with the extraction-architecture
test — all CI-wired with stable required-check names.

Every W3 exit condition is PASS with directly-executed test evidence:
`docs/architecture/wave3-exit-report.md`.

## Units (11, all on `wave3-execution`)

| Unit | Scope | Integrating SHA |
|---|---|---|
| w3-01-exec-arch | shared execution-domain layer (JobKind, JobContext, lifecycle, JobError, limits, event builders, engine guard) | `e38fe6b` |
| w3-02-intake | repository-intake Input Gate | `5413aa8` (+`99228a9` reg) |
| w3-03-patch-runner | agent-runner Execution Gate | `ada77f0` (+`a984b55` reg) |
| w3-04-quality-eval | deterministic Release Gate engine | `dd6e05b` (+`531aa2c` reg) |
| w3-05-observer-discovery | read-only chatgpt-observer + site-discovery | `b7b08dc` (+`89667f1` reg) |
| w3-06-hooks-runtime | FORGE runtime hook ladder + bypass corpus | `55206f8` (+`d808a37` reg/coverage) |
| w3-07-sa-rbac | ADR-0004 SA 3-separation + negative tests | `0dc6484` |
| w3-08-e2e | synthetic-tenant execution E2E | `9213c5e` |
| w3-09-failure | failure-mode 9종 matrix + rollback gate | `fcf60df` |
| w3-10-evals | 9-axis eval harness + extraction-architecture test | `31c624e` |
| w3-11-exit | CI named checks + exit report + PR body | `56c8138` |
| w3-12-f5-integrity | dedicated skill-bundle content-integrity verifier + report/PR corrections | (this unit) |

## Exit evidence

Full condition-by-condition mapping (test `path::name`, integrating SHA,
verdict): `docs/architecture/wave3-exit-report.md`. Includes Job 5종 table,
Hook 5종 table, ServiceAccount permission table, failure-mode 9종 matrix, the
14-step composite E2E evidence, rollback evidence, eval results, CI results, the
verification-method account (per-unit Lead adversarial verification + a final
author-separated independent critic on the integration diff), and production-only
remainder.

## CI

New named required checks (ADR-0018): `evals`, `failure-modes`, `execution-e2e`,
`helm-smoke` — mirroring justfile recipes (SSOT), added alongside the existing
lint/schema-validate/boundaries/unit/integration/contract-compat/contract-lint +
security workflow. helm + kubeconform installed as pinned binaries + checksum
verify (no third-party action). zizmor clean. The `integration` umbrella is
unchanged so the ci_identity lockstep invariant holds.

## Determinism + totals

- Unit lane (`just verify` → blocking): **3081 passed, 26 skipped** — 3/3
  consecutive identical runs.
- Integration lane (`just test-integration`, serial): **184 passed** — 2/2
  identical runs.
- Real-container execution E2E: 7/7 (Temporal + Redpanda + Postgres).

(Totals move with each commit; the exact-HEAD CI result is authoritative on the
PR #4 check-runs view, not frozen here.)

## Real defects found & fixed

- **Orchestrator pre-run signal race** (pre-existing, mis-attributed as flake in
  w2-20): signal-with-start runs the handler before `@workflow.run`; the old
  code asserted on unset `_input`. Fixed (Activity scheduling moved to `run()`),
  deterministic regression test added (verified failing on old code).
- **w3-06 coverage gap**: +58 branch tests to hold the 99% ratchet.
- **F-5 was reported as covered without a dedicated verifier** (w3-12): added a
  real skill-bundle content-integrity verifier (`saena_domain.execution.
  skill_bundle`) enforced fail-closed at the session_start and agent-runner
  boundaries; the failure-mode set is now genuinely 9/9. contract_hash retained
  as a complementary defense.

## Verification method (accurate)

Each unit was authored in an isolated worktree by a separate agent. The per-unit
critic agents did not return structured verdicts over the bus; the Lead did
per-unit adversarial integration verification, and a final **author-separated
independent critic** reviews the w3-12 remediation diff. No "critic PASS" is
claimed ahead of that verdict (recorded in the handoff).

## Process note

w3-03 self-registered its workspace member in root `pyproject.toml`/`uv.lock`
(outside its declared exclusive paths); Integrator completed the missing
`.importlinter` positions. Recorded in the exit report.

## Footer

**No tag. No release. No production deploy. Merge is human-gated.** All 5 W0
safety hooks remain active (Wave 3 spec forbids ending with hooks disabled);
the push/merge precision rules (wave-branch checkpoint push, wave-head→main PR
merge only, no `--admin`) remain in force.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

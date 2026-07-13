# Wave 3 Exit Report — Execution

Branch: `wave3-execution` (from `main` = `9fe9b38`, the merged Wave 2 PR #3).
Status: **PASS** — every Wave 3 exit condition met with directly-executed test
evidence. No exit condition is BLOCKED or NOT IMPLEMENTED.

Authoritative scope: `docs/architecture/implementation-waves.md` §W3 line 36 —
"Job 5종(runner/intake/quality-eval + observer/discovery, SA 3분리 — ADR-0004)
+ hooks 5종 실장 + synthetic tenant Plan→승인→patch→handoff E2E + evals 가동
(추출 아키텍처 테스트 포함) + failure-mode 9종↔fixture 매핑 + rollback 동작
검증 gate." Cross-referenced with k3s spec §5/§8/§10/§11, Algorithm spec §5/§11/§12,
B_Department prompt package §11, ADR-0003/0004/0007/0012/0017/0018/0019.

---

## Exit condition → evidence → integrating SHA → verdict

| Exit condition | Evidence (test `path::name` or artifact) | Integrating SHA | Verdict |
|---|---|---|---|
| Job 5종 실제 구현 | `tests/unit/{svc_repository_intake,svc_agent_runner,svc_quality_eval,svc_observer_discovery}/**` + `packages/domain/src/saena_domain/execution/**` (JobKind closed enum, all 5 kinds) | `e38fe6b`,`5413aa8`,`ada77f0`,`dd6e05b`,`b7b08dc` | PASS |
| ADR-0004 ServiceAccount 3분리 구현·검증 | `tests/unit/deploy/test_service_accounts.py`, `test_rbac_separation.py`; `helm template` renders 5 job SAs `automountServiceAccountToken:false`, 0 ClusterRole/Binding; schema-pinned `executionJobs.*.rbac.clusterAdmin` rejects `--set …=true` | `0dc6484` | PASS |
| hook 5종 실제 runtime 배선 | `packages/hooks-runtime/**` (session_start/pre_tool_use/post_tool_use/subagent_start/before_handoff); `tests/unit/hooks_runtime/**` 172+58 tests; 55-fixture bypass corpus | `55206f8`,`d808a37` | PASS |
| synthetic tenant Plan→승인→patch→handoff E2E | `tests/e2e/execution/test_synthetic_tenant_execution_e2e.py::test_synthetic_tenant_full_execution_e2e`; `tests/integration/execution_e2e/test_temporal_signal_e2e.py`, `test_event_bus_round_trip_e2e.py`, `test_postgres_persistence_e2e.py` (real Temporal + Redpanda + Postgres) | `9213c5e` | PASS |
| eval suite 실제 실행 및 blocking gate | `tests/unit/evals_harness/**` 57 tests, 9 axes, CI job `evals` (`just test-evals`) | `31c624e`,`56c8138` | PASS |
| extraction architecture test | `tests/unit/evals_harness/test_extraction_architecture.py` (importlinter set + real lint-imports subprocess + ast import scan, 3 independent legs) | `31c624e` | PASS |
| 공식 failure-mode 9종 ↔ fixture 1:1 매핑 | `tests/security/failure_mode_matrix.json` + `test_failure_mode_matrix.py` (asserts exactly F-1..F-9, every primary+recovery test node resolvable) | `fcf60df` | PASS |
| failure-mode 전체 테스트 PASS | `tests/security/test_f{1..9}_*.py` (52 tests) + `tests/integration/failure_modes/**` (Postgres-backed) | `fcf60df` | PASS |
| rollback 실제 동작 검증 | `tests/security/test_rollback_worktree_no_partial_commit.py`; `tests/integration/failure_modes/test_rollback_audit_ledger_postgres.py`, `test_rollback_outbox_idempotent_replay_postgres.py` | `fcf60df` | PASS |
| tenant isolation negative tests | `tests/unit/svc_repository_intake/test_negative_cross_tenant.py`; `tests/unit/svc_agent_runner/test_runner_negative.py::test_cross_tenant_worktree_access_denied`; `tests/integration/execution_e2e/test_postgres_persistence_e2e.py::test_tenant_isolation_at_the_postgres_layer` | `5413aa8`,`ada77f0`,`9213c5e` | PASS |
| approval bypass negative tests | `tests/unit/svc_agent_runner/test_approval.py` (unapproved/forged/hash-mismatch refused); `tests/integration/execution_e2e/test_temporal_signal_e2e.py::test_forged_signal_for_a_real_contract_hash_does_not_transition` | `ada77f0`,`9213c5e` | PASS |
| engine_id Google/Gemini 거부 | `packages/domain/src/saena_domain/execution/engine.py::guard_engine_id`; `tests/unit/svc_observer_discovery/test_chatgpt_observer_engine_guard.py` | `e38fe6b`,`b7b08dc` | PASS |
| unit/integration/E2E/evals CI 배선 | `.github/workflows/ci.yml` jobs: lint, schema-validate, boundaries, unit, integration, contract-compat, contract-lint, **evals, failure-modes, execution-e2e, helm-smoke**; `security.yml`: guards, secret-scan, sbom, vuln-scan, actions-lint | `56c8138` | PASS |
| Helm/package smoke | CI `helm-smoke` (`just helm-smoke`: helm lint + template + kubeconform -strict + forgectl preflight) | `56c8138`,`fa5d21f` (helm checksum fix) | PASS |
| architecture boundary | `.importlinter` (independence + leaf contracts, 15 root packages); CI `boundaries` (`lint-imports`) | all integrations | PASS |
| security gates | `secret-scan` (gitleaks full-history; 7 W3 test-fixture FPs suppressed by fingerprint per ADR-0020), `sbom`, `vuln-scan`, hook bypass corpus (LEAK=0 Lead-verified) | `55206f8`,`fa5d21f` | PASS |
| worktree audit clean | `git worktree list` = main only (all unit worktrees destroyed) | — | PASS |
| git status clean | working tree clean at each checkpoint | — | PASS |
| remote wave3-execution 최신 | `origin/wave3-execution` = local HEAD, pushed each checkpoint | — | PASS |

---

## Job 5종 구현표

| JobKind | Pool | ServiceAccount | Read/Write | Package | Key event |
|---|---|---|---|---|---|
| REPOSITORY_INTAKE | runner | saena-repository-intake | read-only Git | `saena_repository_intake` | repo.intaken.v1 |
| AGENT_RUNNER | runner | saena-agent-runner | worktree write, contract-scope | `saena_agent_runner` | patch.unit.completed.v1 |
| QUALITY_EVAL | runner | saena-quality-eval | build-exec only, no Git write | `saena_quality_eval` | quality.gate.passed/failed.v1 |
| CHATGPT_OBSERVER | browser | saena-chatgpt-observer | read-only, no Git cred | `saena_chatgpt_observer` | (PlatformObservation) |
| SITE_DISCOVERY | browser | saena-site-discovery | read-only crawl, no Git cred | `saena_site_discovery` | site.inventory.completed.v1 |

Canonical names per k3s §5.2 + ADR-0004 §3. Pool/SA/read-only enforced in
`saena_domain.execution.JobKind` (w3-01) and the chart RBAC (w3-07).

## Hook 5종 구현표 (FORGE runtime ladder — B_Dept §11)

| Hook | Checks | Timeout | Fail mode | Blocking |
|---|---|---|---|---|
| session_start | verify_run_context, verify_policy_signature, secret_scan | 30s | fail-closed (abort) | contract missing, dirty worktree, detected secrets |
| pre_tool_use | deny_out_of_scope_file_write, deny_deploy_push_cms_dns, deny_unapproved_network_egress, deny_unpinned_dependency_install, require_action_contract_for_write | 5s/call | fail-closed (deny) | deploy cmd, push, prod write, unpinned install, missing contract |
| post_tool_use | record_changed_file_and_patch_unit, append_audit_event, mark_required_tests_dirty | 10s | fail-closed (run unstable) | audit append failure, unexplained changes |
| subagent_start | enforce_role_tool_lease, inject_untrusted_content_policy | 5s | fail-closed | writer role given read-only lease, critic given write creds |
| before_handoff | run_quality_matrix, require_independent_critic, require_rollback_manifest | 60s | fail-closed | missing critic, failed gate, missing rollback, deploy cmd in patch |

This is the FORGE **agent-runtime** ladder (customer-repo execution), distinct
from the W0 `.claude/hooks/` dev-repo safety layer (ADR-0019). Command
normalizer defeats sh -c/bash -c, env prefix (incl. -S), git -c/-C, symlink,
path traversal, encoded/quoted, pipeline, subshell, multiline, indirect
protected-path write. Lead adversarial verification: **LEAK=0** across every
wrapper category; **OVERBLOCK=0** with a valid Action Contract (benign reads +
a commit message containing "push to prod" correctly ALLOW).

## ServiceAccount 권한표 (ADR-0004 §3)

| SA | K8s RBAC | automountToken | Prohibitions verified |
|---|---|---|---|
| saena-agent-runner | none (least privilege) | false | no cluster-admin, no ClusterRoleBinding, no cross-SA Role |
| saena-quality-eval | none | false | no Git-write RBAC, no write verbs |
| saena-repository-intake | none | false | read-only, no write verbs anywhere |
| saena-chatgpt-observer | none | false | no Git credential secret access |
| saena-site-discovery | none | false | no Git credential secret access |

Rendered-manifest tests prove: 0 ClusterRole/ClusterRoleBinding for job SAs,
no shared Role across pools, schema rejection of `--set …rbac.clusterAdmin=true`
on the guarded path, `forgectl preflight` service_account_permissions PASS.

## Failure-mode 9종 매트릭스 (k3s §10)

| # | Mode | Fixture / test | Wired against | Outcome |
|---|---|---|---|---|
| F-1 | Prompt injection | `test_f1_prompt_injection.py` | hooks-runtime pre_tool_use + policy-gate | quarantine, no exec |
| F-2 | Unsupported claim | `test_f2_unsupported_claim.py` | quality-eval content-fidelity gate | block public wording |
| F-3 | Deployment pressure | `test_f3_deployment_pressure.py` | hooks-runtime deny_deploy_push + policy deny | policy deny, handoff only |
| F-4 | Code conflict | `test_f4_code_conflict.py` | agent-runner worktree isolation | isolated worktrees, integrator only |
| F-5 | Skill compromise | `test_f5_skill_compromise.py` | contract_hash / bundle-hash pin mismatch | run blocked |
| F-6 | Secret exposure | `test_f6_secret_exposure.py` | intake secret scan + quality-eval secret gate | redaction and stop |
| F-7 | Quality manipulation | `test_f7_quality_manipulation.py` | quality-eval drift/test-deletion + diff-to-contract | critic rejects |
| F-8 | Scope creep | `test_f8_scope_creep.py` | agent-runner approved_scope / diff-rationality | patch review rejects |
| F-9 | Measurement fraud | `test_f9_measurement_fraud.py` + `measurement_fraud.py` | outcome-layer ≥2-signal evaluator | B-layer success not granted |

CI-blocking completeness gate (`test_failure_mode_matrix.py`) fails if any mode
loses its fixture or a referenced test node stops resolving.

**Framing note (F-5)**: w3-09 marks F-5 "covered" via the `contract_hash`/
bundle-hash mismatch mechanism that exists (hooks-runtime `compute_contract_hash`/
`validate_contract`). The w3-10 eval regression suite (`fm-05-skill-compromise.yaml`)
honestly flags that a *dedicated pinned-skill-bundle-hash verifier* does not yet
exist in-repo (status `gap`, 1 of 9). Both statements are true and non-conflicting:
the generic contract-hash pin is implemented and tested; a skill-specific hash
verifier is a follow-up. Recorded here, not hidden.

## E2E 단계별 증거 (14 steps)

`test_synthetic_tenant_full_execution_e2e` covers steps 1-14 (tenant create →
workspace/project/site context → source intake → PlanContract → Policy Gate →
approval → [Temporal signal in the integration lane] → patch worktree → patch
exec on a REAL git repo → quality eval → VerificationResult → handoff artifact →
[event bus round-trip in the integration lane] → audit hash-chain verify →
lineage → tenant isolation → cleanup). Real components exercised and directly
run by the Lead (Docker present): pure-logic E2E 3 pass; **real-container lane
7/7 pass** (Temporal time-skipping server, Redpanda publish/consume, Postgres
durability + isolation) — NOT mock-only.

## Rollback 증거

- patch-unit rollback leaves no partial commit — `test_rollback_worktree_no_partial_commit.py` (real tmp git repo, main unchanged after rollback)
- audit-chain / approval-ledger / artifact immutability preserved — `test_rollback_audit_ledger_postgres.py`
- outbox replay + idempotency dedup (no double-execution on same idempotency key) — `test_rollback_outbox_idempotent_replay_postgres.py`
- tenant isolation on rollback — covered in the failure_modes suite

## Eval 결과

9 axes, all deterministic (seeded, no wall-clock), CI-blocking in the unit lane
(`evals` job). Each axis carries a false-positive AND false-negative guard fixture
(`test_every_axis_has_at_least_one_discriminating_fixture` enforces it). Evidence-
integrity axis refuses any claim whose `evidence_id` is not in the fixture's
registered evidence set (CLAUDE.md principle 11 — no unregistered evidence, no
external lift claim). 57 harness tests pass.

## CI job 결과 (locally verified where runnable)

lint, schema-validate, boundaries, unit (3081 pass / 26 skip), contract-compat,
contract-lint, **evals** (57 pass), **failure-modes** (52 security + container
proofs), **execution-e2e** (7 container pass), **helm-smoke** (helm lint/template
+ kubeconform 70/70 + forgectl 6/6), guards, secret-scan, sbom, vuln-scan,
actions-lint (zizmor clean). Determinism: unit lane 3/3 identical, integration
lane 2/2 identical (184 pass).

## Critic 발견·수정 내역 (Lead independent verification)

The spawned critic agents did not deliver structured verdicts over the message
bus (idle-pinged without reporting); the Lead therefore performed the required
independent verification directly (CLAUDE.md principle 9), adversarially, per
unit:
- **w3-01**: verified 4 payload builders reject malformed input via codegen
  models; engine guard denies case-variants/whitespace/google/gemini/empty/None;
  every terminal→active transition denied; SUCCEEDED→SUCCEEDED idempotent.
- **w3-03**: verified a contract-named forbidden command (git push/kubectl/helm)
  is still denied with the executor never invoked.
- **w3-06**: verified LEAK=0 across every wrapper defeat and OVERBLOCK=0 under a
  valid contract; confirmed the earlier contract=None denials are correct
  fail-closed, not false positives.
- **w3-07**: verified 0 ClusterRole/Binding for job SAs, all automountToken
  false, schema rejects the guarded clusterAdmin escalation path.
- **w3-08**: ran both E2E lanes (pure + real-container) to prove non-mock.
- **w3-09**: verified the matrix completeness gate resolves all 9 primary+recovery
  test nodes.
- **w3-10**: verified per-axis FP/FN discrimination is enforced and the single
  honest gap is bounded to exactly one.

### Real defects Lead found and fixed during the wave
- **Orchestrator pre-run signal race (pre-existing W2 bug, surfaced integrating
  the W2→main PR)**: Temporal delivers a signal-with-start handler BEFORE
  `@workflow.run`; the old code scheduled the Activity inside the handler behind
  `assert self._input is not None`, dying with ApplicationError. Fixed by moving
  Activity scheduling into `run()`; added a deterministic `start_signal` regression
  test (verified failing against the old code). The w2-20 "flaky under load"
  attribution was incomplete — this was a real ordering bug.
- **w3-06 coverage gap**: the author suite left rule-matcher/normalizer branch
  arms uncovered (unpinned_install 64%, paths 80%, etc.), which would have dropped
  the global ratchet. Integrator added `test_rule_edge_coverage.py` (58 tests)
  covering every branch, holding the 99% ratchet.
- **w3-06 egressProxy / ESO kind (w2-23 carry-over MUST-FIX)**: resolved before
  Wave 2 merge.

### Process deviations recorded (NOTE, non-blocking)
- **w3-03 touched root `pyproject.toml` + `uv.lock`** outside its declared
  exclusive paths (it self-registered the workspace member). Benign (correct
  registration); the Integrator completed the missing `.importlinter` positions.
  Future units must leave ALL root config to the Integrator.

## Production-only 운영 항목 (out of Wave-3-code-scope, honestly not claimed)

- Live cluster deployment of the chart (`helm upgrade --install` against a real
  k3s/k3d) — `deploy/**` + live-cluster operation, not code. helm-smoke proves
  the chart renders and passes preflight; standing it up is an ops action.
- Live dashboard 구동 (real OTel collector + Grafana against live telemetry) —
  dashboards-as-code are delivered and statically validated; live run needs a cluster.
- Real browser pool / Playwright fleet for chatgpt-observer — explicitly Wave 4
  (W3 delivers only the read-only synthetic observer interface).
- A dedicated pinned-skill-bundle-hash verifier (F-5 gap above) — follow-up.
- Production Temporal/Postgres/Redpanda/MinIO topology — infra decision; W3
  proves wiring against real ephemeral test instances only.

## Explicitly OUT (Wave 4, forbidden in W3 — verified absent)

intelligence-worker P0 modules, ClickHouse/vector store, QEEG/TAG projections,
recommendation/optimization/learning, experiment registry, Google/Gemini
providers, customer production deploy, automatic git push. Verified: no such
imports exist in the W3 packages; observer/discovery W4-exclusions are
docstring-only.

## Final verdict

**Wave 3: PASS.** All exit conditions met with executed evidence; no BLOCKED or
NOT IMPLEMENTED remaining. `main` merge / tag / release / production deploy NOT
performed (human-gated). PR draft prepared: `docs/architecture/wave3-pr-body.md`.

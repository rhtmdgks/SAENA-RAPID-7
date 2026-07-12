# agent-orchestrator-service

| Field | Value |
|---|---|
| Service name | `agent-orchestrator-service` |
| Bounded context | MAS / Temporal orchestration |
| Primary responsibility | MAS DAG, state machine, retry, approval pause |
| Owned data | workflow state |
| Consumed contracts | signed Action Contracts |
| Published events | workflow.state.changed.v1 (PROPOSED) |
| Consumed events | plan.contract.approved.v1; quality.gate.* |
| Upstream dependencies | plan-contract-service; forge-console-api |
| Downstream consumers | agent-runner-service; policy-gate-service; quality-eval-service |
| Security boundary | WAITING_APPROVAL→EXECUTING only via signed approval |
| Planned runtime | k3s Deployment + Temporal (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **PARTIALLY IMPLEMENTED (w2-15) — Temporal signal path core, no HTTP surface** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4 (§4.3 run state machine)
- `docs/decisions/ADR-0003-approval-transition-authority-path.md` (Temporal signal path,
  defense-in-depth re-validation authority order)
- `docs/architecture/implementation-waves.md` (W2B exit gate)
- `docs/architecture/resilience.md` (Activity `startToCloseTimeout`/heartbeat formula)

## Status

**PARTIALLY IMPLEMENTED (w2-15)** — `saena_orchestrator` package:

- `workflow_logic.py`: pure run-state-machine core. Import-safe and
  unit-testable WITHOUT a Temporal server. `apply_approval_signal`/
  `require_valid_approval` re-validate an incoming approval signal
  (contract_hash + `PlanSnapshot` immutability + `saena_domain.policy
  .transition`/`guard_execution`) — this IS the ADR-0003 step 4
  defense-in-depth check, re-running the same domain logic Policy Gate
  already ran, over the signal payload.
- `workflow.py`: the ONE Temporal workflow definition for this service,
  `ExecutionWorkflow` (`@workflow.defn`). Lives here under
  `services/platform/agent-orchestrator-service/src/saena_orchestrator/` —
  NOT under root `workflows/**` (protected path; not a workflow-code
  directory in this repo's layout). Starts WAITING_APPROVAL; awaits an
  `approve` signal; only a re-validated-APPROVED signal transitions to
  EXECUTING and schedules the execution Activity. A forged/gate-denied
  signal does not transition — the workflow simply stays WAITING_APPROVAL
  (ADR-0003 "Gate 거부 시 Temporal 전이 불가", proven under a REAL Temporal
  test server — see Testing below). Duplicate signal delivery after
  EXECUTING is a no-op (idempotent replay at the workflow level, on top of
  `saena_domain.policy.transition`'s own idempotent-replay branch). A
  REFUSED signal is recorded into the internal `_seen_decisions` replay
  ledger ONLY if it was accepted (never on refusal) — see "Fixes" below;
  `_plan_state`'s pre-`run()` placeholder is `WAITING_APPROVAL`, not
  `APPROVED`, so an out-of-order signal fails closed by construction. A
  `status` `@workflow.query` handler exposes point-in-time
  `ExecutionWorkflowStatus` (including `last_refused_reason`) without
  waiting for `run()` to return.
- `activities.py`: `run_execution_activity` — a STUB (`@activity.defn`) that
  heartbeats once and returns an accepted result. Real execution work lands
  in W3; this only proves the Activity signature + heartbeat wiring.
- `timeouts.py`: named `startToCloseTimeout`/`heartbeat_timeout` constants —
  the W2B exit gate ("Activity `startToCloseTimeout >= 7200s+buffer` +
  heartbeat 정합"). `ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS = 7200 + 600`
  (buffer chosen by this patch unit); `HEARTBEAT_TIMEOUT_SECONDS = 30`
  (« start-to-close). `validate_timeout_heartbeat_coherence()` asserts both
  bounds; asserted directly in `tests/unit/svc_orchestrator/test_timeouts.py`.
- `signal_client.py`: the `SignalClient` local port — the surface
  plan-contract-service (or any caller holding ADR-0003 authority) uses to
  send the `approve` signal. `TemporalSignalClient` is a real, thin
  implementation over `temporalio.client.Client`; `FakeSignalClient` is an
  in-process test double. No cross-service Python import of
  `saena_plan_contract` (import-linter `services-are-independent` contract) —
  this is the receiving-side contract only.
- Artifacts are referenced only by an opaque `manifest_ref` string (blob
  single-gateway note, `activities.py` docstring) — this service never talks
  to blob storage directly; resolving `manifest_ref` to bytes is
  artifact-registry-service's responsibility, out of this patch unit's scope.

**NOT IMPLEMENTED / OPEN ITEMS (honest gaps, not silently deferred):**

- No HTTP surface (no FastAPI app) — this patch unit is the Temporal signal
  path core only, per its own task scope. `forgectl`/console-facing status
  querying, health checks, and any REST API for this service are future work.
- No production `temporalio.worker.Worker` process wiring (start script,
  task-queue configuration, worker deployment) — only the workflow/activity
  DEFINITIONS exist; running a long-lived Worker against a real (non-test)
  Temporal cluster is deploy-time work, out of this patch unit's scope.
- plan-contract-service does NOT yet call `TemporalSignalClient` (or any
  signal client) — that service's own README already flags "Temporal signal
  dispatch (ADR-0003 step 3) is NOT implemented" on its side. Wiring the
  caller (plan-contract-service constructing a `temporalio.client.Client`
  and either implementing `SignalClient` directly or using
  `TemporalSignalClient`) is a follow-up integration, not part of either
  patch unit's exclusive-write scope.
- `policy.decision.recorded.v1` (ADR-0003 step 2) is carried through this
  module only as an opaque `gate_decision_ref` string on `ApprovalSignal` —
  this workflow does not re-fetch or independently re-verify the Policy Gate
  decision itself (that would reintroduce a live policy-gate-service
  dependency from inside the workflow); it only re-validates the plan/signal
  payload itself (contract_hash, immutability, transition/guard_execution).
- `RunState`/`ExecutionWorkflowStatus` cover only the WAITING_APPROVAL ->
  EXECUTING span of k3s §4.3 that this patch unit owns. QUALITY_GATE,
  REVIEW, HANDOFF_READY, FAILED, REMEDIATION are out of scope (later patch
  units / W3).

## Fixes (critic review)

- **MUST-FIX — `_seen_decisions` ledger poisoning (fixed):** `_handle_approve`
  previously wrote `signal.incoming_decision` into `_seen_decisions`
  UNCONDITIONALLY, before checking whether `apply_approval_signal` refused
  the signal. A forged signal impersonating a real approver's
  `decision_key` with a conflicting decision value was correctly refused
  (no transition), but the ledger write still happened and overwrote that
  approver's prior legitimate entry — permanently poisoning it, so the
  approver's later resubmission of their ORIGINAL decision (including
  ordinary Temporal at-least-once redelivery) would hit
  `ConflictingDecisionError` forever (a one-signal permanent DoS on that
  approver's approval path). Fixed: the ledger write now happens only when
  `result.run_state != RunState.REFUSED`. Regression tests: (integration)
  `test_forged_conflicting_signal_does_not_poison_seen_decisions_ledger`,
  `test_at_least_once_redelivery_of_legit_decision_after_refusal_is_idempotent`
  — both run against a real Temporal test server and use a `status`
  `@workflow.query` (added for this fix) to observe `last_refused_reason`
  precisely; verified to fail against the pre-fix code with the exact
  predicted `ConflictingDecisionError`.
- **SHOULD-FIX — `InconsistentPlanSnapshotError` no longer collapses to
  REFUSED (fixed):** `apply_approval_signal`'s broad
  `except PolicyViolationError` previously also caught
  `InconsistentPlanSnapshotError` (a `PolicyViolationError` subclass),
  silently turning a structural caller wiring bug (exactly one of
  `stored_plan_snapshot`/`plan_snapshot` supplied — both-or-neither is the
  only legal `ApprovalSignal` shape) into an ordinary REFUSED result
  indistinguishable from a merely-forged signal. Fixed: this exception is
  now re-raised explicitly before the broad catch, so it propagates and
  fails loud. Regression test:
  `tests/unit/svc_orchestrator/test_workflow_logic.py::test_inconsistent_plan_snapshot_propagates_not_refused`.
- **SHOULD-FIX — pre-`run()` `_plan_state` placeholder (fixed):** was
  `PlanState.APPROVED`, whose `_ALLOWED_TRANSITIONS` adjacency is empty —
  any signal processed before `run()` sets the real value would have ended
  up REFUSED only incidentally (APPROVED has no outgoing transitions at
  all), not because the machine was deliberately fail-closed for a plan
  that was never actually approved. Changed to `PlanState.WAITING_APPROVAL`
  so an out-of-order signal fails closed by construction (a real,
  is-this-actually-the-plan's-current-state precondition), not via an
  unrelated side effect. Regression test:
  `tests/unit/svc_orchestrator/test_workflow_wiring.py::test_pre_run_plan_state_placeholder_is_waiting_approval_not_approved`.
- **SHOULD-FIX — `gate_decision_ref` opaque trust:** left as-is per critic
  direction (ADR-0003 scope) — see the existing OPEN item above.

## Testing

- `tests/unit/svc_orchestrator/` (36 tests) — pure `workflow_logic` core: full
  §4.3-adjacent `PlanState` transition matrix reused via
  `saena_domain.policy.transition`, signal re-validation (valid ->
  EXECUTING; forged/self-approval/contract-hash-mismatch/immutability-
  violation/gate-denied -> refused, stays WAITING_APPROVAL), idempotent
  signal replay, `guard_execution` reuse (including a monkeypatched
  defense-in-depth branch that is not reachable via `transition()`'s public
  contract today), timeout/heartbeat constant assertions,
  `InconsistentPlanSnapshotError` propagation (not collapsed to REFUSED),
  and the `_plan_state` pre-`run()` placeholder value. Runs WITHOUT a
  Temporal server.
- `tests/integration/orchestrator/` (6 tests) — **ran successfully against a
  REAL embedded Temporal test-server process** via
  `temporalio.testing.WorkflowEnvironment.start_time_skipping()` (not a
  mock of the Temporal client/server). Covers: a valid approval signal
  driving WAITING_APPROVAL -> EXECUTING with the Activity scheduled and
  completed; a forged self-approval signal leaving the workflow RUNNING
  (never transitioning) and a subsequent legitimate signal still able to
  complete it; duplicate signal delivery after EXECUTING as a no-op; a
  forged signal impersonating a real approver's `decision_key` with a
  conflicting decision NOT poisoning that approver's `_seen_decisions`
  replay slot (critic MUST-FIX regression); at-least-once redelivery of a
  legitimate decision remaining idempotent-accepted after an unrelated
  refusal; and `TemporalSignalClient` driving the same transition over a
  real `temporalio.client.Client`. Marked `pytest.mark.integration`
  (registered locally in this directory's `conftest.py`); a startup probe
  with a bounded timeout skips the whole module with the captured exception
  if the test-server binary cannot be obtained/started — this did NOT occur
  in this patch unit's own verification run. The two MUST-FIX regression
  tests were verified to actually FAIL (with the exact predicted
  `ConflictingDecisionError`) when run against a temporarily reintroduced
  pre-fix (unconditional-ledger-write) version of `workflow.py`, confirming
  they are load-bearing.

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
  `saena_domain.policy.transition`'s own idempotent-replay branch).
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

## Testing

- `tests/unit/svc_orchestrator/` — pure `workflow_logic` core: full
  §4.3-adjacent `PlanState` transition matrix reused via
  `saena_domain.policy.transition`, signal re-validation (valid ->
  EXECUTING; forged/self-approval/contract-hash-mismatch/immutability-
  violation/gate-denied -> refused, stays WAITING_APPROVAL), idempotent
  signal replay, `guard_execution` reuse (including a monkeypatched
  defense-in-depth branch that is not reachable via `transition()`'s public
  contract today), timeout/heartbeat constant assertions. Runs WITHOUT a
  Temporal server.
- `tests/integration/orchestrator/` — **ran successfully against a REAL
  embedded Temporal test-server process** via
  `temporalio.testing.WorkflowEnvironment.start_time_skipping()` (not a
  mock of the Temporal client/server). Covers: a valid approval signal
  driving WAITING_APPROVAL -> EXECUTING with the Activity scheduled and
  completed; a forged self-approval signal leaving the workflow RUNNING
  (never transitioning) and a subsequent legitimate signal still able to
  complete it; duplicate signal delivery after EXECUTING as a no-op; and
  `TemporalSignalClient` driving the same transition over a real
  `temporalio.client.Client`. Marked `pytest.mark.integration`
  (registered locally in this directory's `conftest.py`); a startup probe
  with a bounded timeout skips the whole module with the captured exception
  if the test-server binary cannot be obtained/started — this did NOT occur
  in this patch unit's own verification run.

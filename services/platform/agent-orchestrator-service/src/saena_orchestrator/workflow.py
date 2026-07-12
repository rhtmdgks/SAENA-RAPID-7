"""`ExecutionWorkflow` — the Temporal workflow definition for this service.

CRITICAL (per this unit's task boundary): this is the ONLY Temporal workflow
definition for `agent-orchestrator-service`. It lives here, inside
`services/platform/agent-orchestrator-service/src/saena_orchestrator/`, NOT
under the root `workflows/**` directory — that root path is PROTECTED
(CLAUDE.md protected paths) and is not a Temporal-workflow-code directory in
this repo's layout.

Starts in WAITING_APPROVAL and awaits an `approve` signal (ADR-0003 step 3:
plan-contract-service sends this signal directly, event bus bypassed). On
receipt, `workflow_logic.apply_approval_signal` re-validates the signal
(defense-in-depth, ADR-0003 step 4) over the SAME `saena_domain.policy` logic
Policy Gate already ran. Only a signal that re-validates as APPROVED
transitions the workflow to EXECUTING and schedules `run_execution_activity`.
A forged/gate-denied/stale signal does NOT transition — the workflow simply
stays in WAITING_APPROVAL (k3s spec §4.3 / W2B exit gate: "Gate 거부 시
Temporal 전이 불가").

Idempotent signal replay: the workflow keeps its own `_seen_decisions` map
(mirroring `saena_domain.policy.transition`'s own `seen_decisions` idempotency
mechanism) so the SAME approval signal delivered twice (Temporal signals are
at-least-once at the transport level, per k3s §4.1) produces exactly ONE
state transition — the second delivery replays through `transition()`'s own
idempotent-replay branch and, having already reached EXECUTING, is a no-op
(see `_handle_approve` below: once `_run_state` is EXECUTING, further signals
are ignored outright, which is itself the single-transition guarantee at the
workflow level, on top of `transition()`'s own idempotency at the domain
level).
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_domain.policy import DecisionRecord, PlanState
from temporalio import workflow
from temporalio.workflow import ActivityHandle

from saena_orchestrator.activities import ExecutionActivityInput, ExecutionActivityResult
from saena_orchestrator.timeouts import ACTIVITY_START_TO_CLOSE_TIMEOUT, HEARTBEAT_TIMEOUT
from saena_orchestrator.workflow_logic import ApprovalSignal, RunState, apply_approval_signal

APPROVE_SIGNAL_NAME = "approve"


@dataclass(frozen=True, slots=True)
class ExecutionWorkflowInput:
    """Workflow start payload — the run this workflow instance governs."""

    contract_hash: str
    manifest_ref: str
    proposer_actor_id: str


@dataclass(frozen=True, slots=True)
class ExecutionWorkflowStatus:
    """Queryable projection of the workflow's current state (for tests/ops;
    no `@workflow.query` handler is exposed beyond what tests need directly
    via workflow state in the time-skipping harness — kept as a plain
    dataclass so it stays serializable and simple).
    """

    run_state: RunState
    plan_state: PlanState
    last_refused_reason: str | None
    activity_result: ExecutionActivityResult | None


@workflow.defn
class ExecutionWorkflow:
    """WAITING_APPROVAL -> EXECUTING via `approve` signal only (ADR-0003)."""

    def __init__(self) -> None:
        self._input: ExecutionWorkflowInput | None = None
        self._run_state: RunState = RunState.WAITING_APPROVAL
        self._plan_state: PlanState = PlanState.APPROVED  # set on run(); placeholder pre-run
        self._last_refused_reason: str | None = None
        self._activity_result: ExecutionActivityResult | None = None
        self._activity_task: ActivityHandle[ExecutionActivityResult] | None = None
        self._seen_decisions: dict[tuple[str, str], DecisionRecord] = {}

    @workflow.run
    async def run(self, workflow_input: ExecutionWorkflowInput) -> ExecutionWorkflowStatus:
        self._input = workflow_input
        # The workflow's plan starts WAITING_APPROVAL (k3s §4.3): the
        # ChangePlan has already been submitted for review by the time this
        # workflow is started (PROPOSED->WAITING_APPROVAL happens upstream,
        # in plan-contract-service, before the workflow is even started —
        # out of this workflow's scope, which begins at WAITING_APPROVAL).
        self._plan_state = PlanState.WAITING_APPROVAL
        self._run_state = RunState.WAITING_APPROVAL

        # Wait until a valid approval signal has driven run_state to
        # EXECUTING. `_handle_approve` (the @workflow.signal handler) is the
        # only mutator of `_run_state`; once it observes EXECUTING it also
        # schedules the activity itself (see below) — the run() method only
        # needs to wait for that to happen and then await the scheduled
        # activity's completion, which is tracked via `_activity_task`.
        await workflow.wait_condition(lambda: self._run_state == RunState.EXECUTING)

        if self._activity_task is not None:
            self._activity_result = await self._activity_task

        return ExecutionWorkflowStatus(
            run_state=self._run_state,
            plan_state=self._plan_state,
            last_refused_reason=self._last_refused_reason,
            activity_result=self._activity_result,
        )

    @workflow.signal(name=APPROVE_SIGNAL_NAME)
    def _handle_approve(self, signal: ApprovalSignal) -> None:
        """Signal handler — re-validates `signal` (defense-in-depth,
        ADR-0003 step 4) and, ONLY on a valid approval, transitions to
        EXECUTING and schedules the execution Activity.

        Deliberately synchronous (a plain, non-`async def`
        `@workflow.signal` handler) — the re-validation itself
        (`apply_approval_signal`) is pure/CPU-only and needs no `await`.
        Scheduling the Activity uses `workflow.start_activity`, which
        schedules the Activity and returns an `ActivityHandle` immediately
        (it does not block/await completion) — that handle is stashed on
        `self._activity_task` so `run()` can `await` it once
        `wait_condition` observes `_run_state == EXECUTING`.
        """
        if self._run_state == RunState.EXECUTING:
            # Idempotent replay guard at the workflow level: once EXECUTING,
            # further approve signals (duplicate delivery, k3s §4.1
            # at-least-once) are no-ops — the single-transition guarantee.
            return

        result = apply_approval_signal(
            self._plan_state, signal, seen_decisions=self._seen_decisions
        )
        # Record this decision into the idempotency map exactly as
        # transition() would expect a caller-maintained store to (mirrors
        # saena_domain.policy.transition's own seen_decisions contract).
        self._seen_decisions[signal.incoming_decision.decision_key] = signal.incoming_decision
        self._plan_state = result.plan_state

        if result.run_state != RunState.EXECUTING:
            # Refused (forged/gate-denied signal) or still WAITING_APPROVAL
            # (quorum pending) — do NOT transition. Workflow stays put
            # (ADR-0003 "Gate 거부 시 Temporal 전이 불가").
            self._last_refused_reason = result.refused_reason
            return

        self._run_state = RunState.EXECUTING
        assert self._input is not None  # run() always sets this before signals are processed
        self._activity_task = workflow.start_activity(
            "run_execution_activity",
            ExecutionActivityInput(
                contract_hash=self._input.contract_hash,
                manifest_ref=self._input.manifest_ref,
            ),
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
        )


__all__ = [
    "APPROVE_SIGNAL_NAME",
    "ExecutionWorkflow",
    "ExecutionWorkflowInput",
    "ExecutionWorkflowStatus",
]

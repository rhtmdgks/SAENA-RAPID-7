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

`_seen_decisions` ledger-poisoning fix (critic MUST-FIX): `_handle_approve`
records a decision into `_seen_decisions` ONLY when `apply_approval_signal`'s
outcome is NOT `RunState.REFUSED` — never unconditionally. A REFUSED signal
(forged, self-approval, tampered contract_hash, impersonating a real
approver's `decision_key` with a conflicting decision value, ...) is, by
definition, NOT authoritative over that `decision_key`'s replay slot; writing
it into the ledger anyway would let a single forged/conflicting signal
permanently overwrite — and thereby poison — a legitimate approver's prior
recorded decision, so that approver's later resubmission of their ORIGINAL,
genuine decision (including ordinary at-least-once redelivery of the exact
same signal) would incorrectly hit `transition()`'s own
`ConflictingDecisionError` forever (a permanent, one-signal denial-of-service
on that approver's approval path). Only a decision that `transition()` itself
accepted as consistent (EXECUTING, or a legitimate WAITING_APPROVAL
quorum-pending outcome) is written to `_seen_decisions`.
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
    """Point-in-time projection of the workflow's current state. Returned by
    `run()` on completion AND by the `status` `@workflow.query` handler
    (below) for point-in-time observability while the workflow is still
    WAITING_APPROVAL/RUNNING — added so a caller/test can distinguish "the
    last-processed signal was REFUSED" from "the last-processed signal was
    legitimately accepted but quorum-pending" without waiting for `run()` to
    return (both leave the workflow externally RUNNING; `last_refused_reason`
    is the only observable difference).
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
        # Placeholder pre-run() value (critic SHOULD-FIX 2): WAITING_APPROVAL,
        # NOT APPROVED. A signal processed before run() sets the real value
        # at line ~94 would otherwise start from PlanState.APPROVED, whose
        # _ALLOWED_TRANSITIONS adjacency is empty — any such signal would
        # incidentally end up REFUSED only because APPROVED has no outgoing
        # transitions, not because the machine is deliberately closed. Using
        # WAITING_APPROVAL here means an early signal fails closed BY
        # CONSTRUCTION (WAITING_APPROVAL is a real, is-this-actually-the-
        # plan's-current-state precondition each of transition()'s guards
        # checks), not incidentally via an unrelated empty-adjacency side
        # effect of a state that was never true.
        self._plan_state: PlanState = PlanState.WAITING_APPROVAL
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
        #
        # Deliberately NO state (re-)initialization here: __init__ already
        # sets both to WAITING_APPROVAL, and Temporal delivers a signal that
        # arrives in the same workflow task as start BEFORE `run()` executes
        # — a legitimate approval processed in that window has already driven
        # `_run_state` to EXECUTING, and resetting it here would swallow that
        # accepted transition (the workflow would then wait forever on a
        # decision that `_seen_decisions` says was already consumed). This
        # exact pre-run-signal ordering was the root cause of the
        # intermittent `test_duplicate_approve_signal_after_executing_is_a_
        # no_op` CI failure (AssertionError in the signal handler, 2026-07-13).

        # Wait until a valid approval signal has driven run_state to
        # EXECUTING. `_handle_approve` (the @workflow.signal handler) is the
        # only mutator of `_run_state`. Scheduling the execution Activity
        # happens HERE, not in the signal handler: `run()` is the only place
        # `self._input` is guaranteed to be set (a handler running before
        # `run()` has no input to build the Activity payload from — the old
        # in-handler scheduling asserted on that and died). `_handle_approve`'s
        # EXECUTING no-op guard keeps the transition single-shot, so this
        # schedules exactly once.
        await workflow.wait_condition(lambda: self._run_state == RunState.EXECUTING)

        self._activity_task = workflow.start_activity(
            "run_execution_activity",
            ExecutionActivityInput(
                contract_hash=self._input.contract_hash,
                manifest_ref=self._input.manifest_ref,
            ),
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
        )
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
        EXECUTING. Activity scheduling is `run()`'s job (see there): a
        handler may execute BEFORE `run()` when Temporal delivers the signal
        in the same workflow task as start, so this handler must be safe to
        run with `self._input` still unset — it therefore touches only the
        state machine, never the Activity payload.

        Deliberately synchronous (a plain, non-`async def`
        `@workflow.signal` handler) — the re-validation itself
        (`apply_approval_signal`) is pure/CPU-only and needs no `await`.
        """
        if self._run_state == RunState.EXECUTING:
            # Idempotent replay guard at the workflow level: once EXECUTING,
            # further approve signals (duplicate delivery, k3s §4.1
            # at-least-once) are no-ops — the single-transition guarantee.
            return

        result = apply_approval_signal(
            self._plan_state, signal, seen_decisions=self._seen_decisions
        )
        self._plan_state = result.plan_state

        if result.run_state == RunState.REFUSED:
            # critic MUST-FIX: do NOT record a REFUSED decision into
            # _seen_decisions. A forged/self-approval/tampered signal that
            # impersonates a legitimate approver (same decision_key,
            # different decision value) would otherwise OVERWRITE that
            # approver's prior legitimate entry — apply_approval_signal
            # already refused the transition, but writing the ledger
            # unconditionally here would permanently poison
            # decision_key's idempotency-replay slot: the real approver's
            # later resubmission (including ordinary Temporal
            # at-least-once redelivery of their ORIGINAL decision) would
            # then hit transition()'s own ConflictingDecisionError forever
            # — a single forged signal would permanently block a
            # legitimate approver (DoS on the approval path). Only
            # accepted/valid decisions (EXECUTING or a legitimate
            # WAITING_APPROVAL quorum-pending outcome) are recorded, below.
            self._last_refused_reason = result.refused_reason
            return

        # Record this decision into the idempotency map exactly as
        # transition() would expect a caller-maintained store to (mirrors
        # saena_domain.policy.transition's own seen_decisions contract) —
        # ONLY for a non-REFUSED outcome (see guard above).
        self._seen_decisions[signal.incoming_decision.decision_key] = signal.incoming_decision

        if result.run_state != RunState.EXECUTING:
            # Still WAITING_APPROVAL (quorum pending) — a legitimate,
            # accepted-but-insufficient decision. Do NOT transition; the
            # workflow stays put (ADR-0003 "Gate 거부 시 Temporal 전이 불가"
            # applies to REFUSED above, not to this legitimate pending case).
            self._last_refused_reason = result.refused_reason
            return

        # Transition only — Activity scheduling lives in `run()` (the only
        # place `self._input` is guaranteed set; Temporal runs a signal
        # handler BEFORE `run()` when the signal lands in the same workflow
        # task as start, so scheduling here would race on `_input` — the
        # 2026-07-13 intermittent CI AssertionError). `run()`'s
        # `wait_condition` observes this write and schedules exactly once.
        self._run_state = RunState.EXECUTING

    @workflow.query
    def status(self) -> ExecutionWorkflowStatus:
        """Point-in-time status query — lets a caller (or a test, without
        waiting for `run()` to return) observe `run_state`/`plan_state`/
        `last_refused_reason` while the workflow is still WAITING_APPROVAL,
        distinguishing "the last-processed signal was REFUSED" from "the
        last-processed signal was legitimately accepted but quorum-pending"
        (both leave the workflow RUNNING/WAITING_APPROVAL from the outside,
        but `last_refused_reason` differs: non-None only for the REFUSED
        case, per `_handle_approve`'s guard above).
        """
        return ExecutionWorkflowStatus(
            run_state=self._run_state,
            plan_state=self._plan_state,
            last_refused_reason=self._last_refused_reason,
            activity_result=self._activity_result,
        )


__all__ = [
    "APPROVE_SIGNAL_NAME",
    "ExecutionWorkflow",
    "ExecutionWorkflowInput",
    "ExecutionWorkflowStatus",
]

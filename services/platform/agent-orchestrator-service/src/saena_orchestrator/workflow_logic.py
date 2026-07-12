"""Pure run-state-machine core — import-safe, unit-testable WITHOUT a Temporal
server.

Authority path (ADR-0003): B signed approval -> Policy Gate pre-verification
(recorded, authoritative) -> only on Policy Gate approval does
plan-contract-service signal Temporal directly. Temporal's OWN re-verification
on receipt of that signal is defense-in-depth, NOT primary authority (ADR-0003
step 4) — this module IS that defense-in-depth re-validation function. It
re-runs the SAME `saena_domain.policy` decision logic (`transition`,
`guard_execution`) that plan-contract-service/Policy Gate already ran, over
the payload the workflow received in the signal, so a forged or stale signal
(wrong contract_hash, tampered plan_snapshot, wrong gate_decision_ref) is
caught here even if it somehow bypassed the primary path.

k3s spec §4.3: `WAITING_APPROVAL -> EXECUTING` only via signed approval; "both
Policy Gate and Temporal workflow verify this transition independently" — this
module models the Temporal-side half of that dual verification, at the
RUN level (the workflow's own lifecycle state), distinct from
`saena_domain.policy.PlanState` (the ChangePlan APPROVAL sub-machine that
`saena_domain.policy.transition` itself operates over). A `RunState` only ever
becomes EXECUTING after this module observes the underlying `PlanState`
resolve to APPROVED via a validated signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from saena_domain.policy import (
    DecisionRecord,
    ExecutionBlockedError,
    InvalidTransitionError,
    PlanSnapshot,
    PlanState,
    PolicyViolationError,
    guard_execution,
    transition,
)
from saena_domain.policy.two_person import ApproverRecord

from saena_orchestrator.errors import SignalRefusedError


class RunState(StrEnum):
    """Run-level lifecycle states this workflow drives (k3s §4.3 span this
    patch unit owns: WAITING_APPROVAL -> EXECUTING). Other k3s §4.3 states
    (QUALITY_GATE, REVIEW, ...) belong to later patch units / W3 and are out
    of scope here — this workflow starts in WAITING_APPROVAL and this
    module's responsibility ends at EXECUTING (activity scheduled) or a
    terminal non-approval outcome.
    """

    WAITING_APPROVAL = "waiting_approval"
    EXECUTING = "executing"
    REFUSED = "refused"  # signal re-validation failed; stays effectively
    # WAITING_APPROVAL from the caller's perspective (see AppprovalSignal
    # handling below) — this state exists only for this module's own
    # observability of the LAST refusal, not as a k3s §4.3 terminal state.


@dataclass(frozen=True, slots=True)
class ApprovalSignal:
    """Payload carried by the Temporal `approve` signal (ADR-0003 step 3: the
    signal plan-contract-service sends directly, bypassing the event bus).

    Mirrors ADR-0003's own enumeration ("approve signal carrying
    {contract_hash, plan_snapshot, gate_decision_ref}" — task instruction 2):
    - `contract_hash` / `incoming_decision`: fed straight into
      `saena_domain.policy.transition` for re-validation.
    - `plan_snapshot` / `stored_plan_snapshot`: fed into `transition`'s
      `presented_plan`/`stored_plan` immutability choke point.
    - `gate_decision_ref`: opaque reference to the Policy Gate decision that
      authorized this signal (`policy.decision.recorded.v1`, ADR-0003 step
      2) — this module does not re-fetch or re-verify the gate decision
      itself (that would re-introduce a live dependency on policy-gate-service
      from inside the workflow, which is out of scope / against the
      no-cross-service-import constraint); it is carried through only so the
      resulting audit record can reference which gate decision authorized
      the signal.
    """

    contract_hash: str
    proposer_actor_id: str
    approvals: tuple[ApproverRecord, ...]
    high_risk: bool
    decided_at: str
    incoming_decision: DecisionRecord
    plan_snapshot: PlanSnapshot
    stored_plan_snapshot: PlanSnapshot
    gate_decision_ref: str


@dataclass(frozen=True, slots=True)
class RunTransitionResult:
    """Outcome of applying one ApprovalSignal to the run state machine."""

    run_state: RunState
    plan_state: PlanState
    refused_reason: str | None = None


def apply_approval_signal(
    current_plan_state: PlanState,
    signal: ApprovalSignal,
    *,
    seen_decisions: dict[tuple[str, str], DecisionRecord] | None = None,
) -> RunTransitionResult:
    """Re-validate an incoming approval signal (ADR-0003 step 4 defense-in-
    depth) and compute the resulting RunState.

    This is the single function the Temporal workflow calls from its signal
    handler. It NEVER raises for an expected refusal (wrong contract_hash,
    forged/self-approval, immutability violation, insufficient quorum,
    invalid current-state) — all of those collapse to
    `RunTransitionResult(run_state=RunState.REFUSED, ...)` so the workflow's
    signal handler can simply not-transition and stay in WAITING_APPROVAL
    (ADR-0003 "Gate 거부 시 Temporal 전이 불가"). It DOES let
    `saena_domain.policy` structural/programmer errors
    (`InconsistentPlanSnapshotError`) propagate, since those indicate a
    caller bug in this module's own wiring, not an untrusted-signal outcome.
    """
    try:
        outcome = transition(
            current_plan_state,
            contract_hash=signal.contract_hash,
            proposer_actor_id=signal.proposer_actor_id,
            approvals=signal.approvals,
            high_risk=signal.high_risk,
            decided_at=signal.decided_at,
            seen_decisions=seen_decisions,
            incoming_decision=signal.incoming_decision,
            stored_plan=signal.stored_plan_snapshot,
            presented_plan=signal.plan_snapshot,
        )
    except InvalidTransitionError as exc:
        return RunTransitionResult(
            run_state=RunState.REFUSED,
            plan_state=current_plan_state,
            refused_reason=str(exc),
        )
    except PolicyViolationError as exc:
        # ContractHashViolationError, ConflictingDecisionError: these are
        # also refusals from the signal's point of view (a tampered/forged
        # signal), not this module's own bug — refuse, do not raise.
        return RunTransitionResult(
            run_state=RunState.REFUSED,
            plan_state=current_plan_state,
            refused_reason=str(exc),
        )

    if outcome.state != PlanState.APPROVED:
        # WAITING_APPROVAL (quorum pending) or REJECTED/EXPIRED/CANCELLED:
        # none of these authorize EXECUTING. The workflow stays put; this is
        # not necessarily a "refusal" in the forged-signal sense (e.g.
        # legitimate quorum-pending), so run_state reports WAITING_APPROVAL
        # rather than REFUSED unless the plan resolved to a rejection-shaped
        # terminal state.
        if outcome.state == PlanState.WAITING_APPROVAL:
            return RunTransitionResult(
                run_state=RunState.WAITING_APPROVAL,
                plan_state=outcome.state,
            )
        return RunTransitionResult(
            run_state=RunState.REFUSED,
            plan_state=outcome.state,
            refused_reason=f"plan resolved to {outcome.state!r}, not approved",
        )

    # PlanState.APPROVED: re-run the execution guard (defense-in-depth over
    # guard_execution itself, ADR-0003 step 4) before authorizing EXECUTING.
    try:
        guard_execution(outcome.state, approval_decision=signal.incoming_decision.decision)
    except ExecutionBlockedError as exc:
        return RunTransitionResult(
            run_state=RunState.REFUSED,
            plan_state=outcome.state,
            refused_reason=str(exc),
        )

    return RunTransitionResult(run_state=RunState.EXECUTING, plan_state=outcome.state)


def require_valid_approval(
    current_plan_state: PlanState,
    signal: ApprovalSignal,
    *,
    seen_decisions: dict[tuple[str, str], DecisionRecord] | None = None,
) -> RunTransitionResult:
    """Same re-validation as `apply_approval_signal`, but raises
    `SignalRefusedError` instead of returning a REFUSED result — used by
    call sites (e.g. the Temporal workflow's signal handler) that want
    exception-based control flow (skip the activity-scheduling branch
    entirely) rather than branching on `RunTransitionResult.run_state`.
    """
    result = apply_approval_signal(current_plan_state, signal, seen_decisions=seen_decisions)
    if result.run_state != RunState.EXECUTING:
        raise SignalRefusedError(result.refused_reason or f"run_state={result.run_state!r}")
    return result


__all__ = [
    "ApprovalSignal",
    "RunState",
    "RunTransitionResult",
    "apply_approval_signal",
    "require_valid_approval",
]

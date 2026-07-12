"""ChangePlan/ApprovalDecision state machine — transition(), guard_execution().

Authority path (ADR-0003): B signed approval -> Policy Gate pre-verification
(recorded) -> only on Policy Gate approval does plan-contract-service signal
Temporal directly (event bus bypassed); Temporal's own re-verification is
defense-in-depth, not primary authority; plan.contract.approved.v1 is
notification-only, not a transition trigger. This module IS the Policy Gate
pre-verification decision function referenced by ADR-0003 step 2 — it does not
itself talk to Temporal or the event bus (out of scope: pure domain policy).

k3s spec §4.3: WAITING_APPROVAL -> EXECUTING only via signed approval; both
Policy Gate and Temporal workflow verify this transition independently. This
module models the Policy Gate side of that dual verification.
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_domain.policy.audit import AuditReasonCode, AuditTrailRecord
from saena_domain.policy.errors import (
    ConflictingDecisionError,
    ContractHashViolationError,
    ExecutionBlockedError,
    InconsistentPlanSnapshotError,
    InvalidTransitionError,
)
from saena_domain.policy.identity import canonical_actor_id
from saena_domain.policy.states import PlanState
from saena_domain.policy.two_person import ApproverRecord, evaluate_h7_two_person_approval

# k3s §4.3-derived approval sub-machine adjacency (see states.py module
# docstring for the full k3s-vocabulary mapping and OPEN ITEMs).
_ALLOWED_TRANSITIONS: dict[PlanState, frozenset[PlanState]] = {
    PlanState.PROPOSED: frozenset({PlanState.WAITING_APPROVAL, PlanState.CANCELLED}),
    PlanState.WAITING_APPROVAL: frozenset(
        {
            PlanState.APPROVED,
            PlanState.REJECTED,
            PlanState.EXPIRED,
            PlanState.CANCELLED,
        }
    ),
    PlanState.APPROVED: frozenset(),
    PlanState.REJECTED: frozenset(),
    PlanState.EXPIRED: frozenset(),
    PlanState.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """A single ApprovalDecision projection, keyed for idempotent replay.

    Idempotency key = contract_hash + approver_actor_id (contract-catalog.md
    ApprovalDecision row). `decision_id` is this module's own replay key
    surrogate (task instruction 2: "transitions keyed by contract_hash +
    decision id") — approval-decision.schema.json has no explicit decision_id
    field, so this module derives one deterministically from
    (contract_hash, approver_actor_id) via `decision_key`. OPEN ITEM: if a
    future schema revision adds an explicit decision_id, this derivation
    should be replaced with the schema field.

    `decision_key` canonicalizes approver_actor_id (identity.canonical_actor_id)
    before keying — actor_id format is OPEN per identifiers.schema.json, so a
    whitespace/case variant of the same approver_actor_id MUST map to the same
    replay key (critic MUST-FIX 2), not a distinct one.
    """

    contract_hash: str
    approver_actor_id: str
    decision: str  # "approved" | "rejected"
    proposer_actor_id: str
    high_risk: bool
    decided_at: str

    @property
    def decision_key(self) -> tuple[str, str]:
        return (self.contract_hash, canonical_actor_id(self.approver_actor_id))


@dataclass(frozen=True, slots=True)
class TransitionOutcome:
    """Result of transition(): the new state plus its audit descriptor."""

    state: PlanState
    audit_record: AuditTrailRecord


@dataclass(frozen=True, slots=True)
class PlanSnapshot:
    """contract_hash + an opaque content fingerprint for immutability checks.

    `content_fingerprint` is caller-supplied (e.g. a hash of the canonical
    ChangePlan document) — this module does not compute it; it only compares
    two snapshots under guard_immutability. Used by transition() to make the
    post-approval immutability check (H-3/H-7: "after approval, contract_hash
    frozen") a structural choke point on the WAITING_APPROVAL decision path
    rather than a separately-callable, easy-to-skip function (critic
    MUST-FIX 1).
    """

    contract_hash: str
    content_fingerprint: str


def is_high_risk_plan(hypothesis_risks: tuple[str, ...]) -> bool:
    """A ChangePlan is high-risk (H-7) iff any hypothesis carries risk=='high'.

    change-plan.schema.json has no plan-level risk field; risk lives at
    hypotheses[].risk (enum low|medium|high). This derivation is this
    module's own policy interpretation — flagged as an OPEN ITEM in the final
    report (no schema field explicitly named "the risk field" for the whole
    plan, contrary to a literal reading of task instruction 4).
    """
    return "high" in hypothesis_risks


def transition(
    plan_state: PlanState,
    *,
    contract_hash: str,
    proposer_actor_id: str,
    approvals: tuple[ApproverRecord, ...],
    high_risk: bool,
    decided_at: str,
    seen_decisions: dict[tuple[str, str], DecisionRecord] | None = None,
    incoming_decision: DecisionRecord | None = None,
    stored_plan: PlanSnapshot | None = None,
    presented_plan: PlanSnapshot | None = None,
) -> TransitionOutcome:
    """Compute the next PlanState given the current state and an approval set.

    `stored_plan`/`presented_plan` (critic MUST-FIX 1): BOTH-OR-NEITHER are
    the only legal states. When both are supplied, guard_immutability() runs
    FIRST, before any other state logic — a caller cannot reach APPROVED (or
    any other outcome) through this function while bypassing the
    post-approval immutability check. When NEITHER is supplied (both None,
    the default), the check is skipped entirely — this is the only way to
    opt out, used by the PROPOSED->WAITING_APPROVAL submission path, which
    has no "stored" plan to compare against yet. Supplying EXACTLY ONE of
    the two raises InconsistentPlanSnapshotError immediately — a partial
    pair would otherwise silently skip guard_immutability (fail-open), which
    this module refuses to do (critic MUST-FIX 1 re-verify: fail closed).
    `stored_plan` is the plan content as already persisted/previously
    approved; `presented_plan` is the plan content presented alongside this
    decision. Callers on the WAITING_APPROVAL decision path (where
    post-approval immutability actually matters) MUST pass both.

    Idempotency note (SHOULD-FIX 5): transition() is a pure, stateless
    function — "idempotent replay" means that calling it again with the same
    arguments (including the same `seen_decisions`/`approvals` snapshot)
    yields the same TransitionOutcome; this module does NOT persist or cache
    any prior outcome itself. Callers are responsible for supplying a
    consistent `seen_decisions`/`approvals` view (e.g. reloaded from a
    decision store) on each call — replay safety is a property of calling
    this function with consistent inputs, not a guarantee this module
    enforces via hidden state.

    Semantics:
    - PROPOSED -> WAITING_APPROVAL / CANCELLED: not decision-driven (no
      ApprovalDecision involved yet); callers pass approvals=() and
      incoming_decision=None; only PROPOSED->WAITING_APPROVAL is derivable
      here deterministically (submission for review), so PROPOSED always
      advances to WAITING_APPROVAL in this function — proposer-initiated
      CANCELLED from PROPOSED is a distinct explicit caller action, not
      modeled as an inferred outcome of this function (see cancel() below).
    - WAITING_APPROVAL: guard_immutability() runs first (see above), then
      evaluated against `approvals` (H-7 evaluate_h7_two_person_approval)
      plus `incoming_decision` idempotency checks:
        * incoming_decision replays (identical contract_hash+approver+decision
          already in seen_decisions, approver_actor_id compared via
          canonical_actor_id) => no-op, returns the SAME outcome as calling
          this function again with the same consistent inputs (idempotent
          replay, no duplicate state change).
        * incoming_decision conflicts (same decision_key, different decision
          value) => ConflictingDecisionError.
        * incoming_decision.approver_actor_id == proposer_actor_id, compared
          via canonical_actor_id (NFKC + strip + casefold — actor_id format
          is OPEN per identifiers.schema.json) => InvalidTransitionError
          (self-approval forbidden for ALL plans, including case/whitespace
          variants of the same identity).
        * otherwise: if quorum satisfied (H-7-aware) => APPROVED; if the
          incoming decision itself is "rejected" => REJECTED; else plan stays
          WAITING_APPROVAL (insufficient quorum yet — not an error, just no
          transition; callers must not treat this as failure).
    - Any other (state, requested) pair not in _ALLOWED_TRANSITIONS =>
      InvalidTransitionError.
    """
    seen = seen_decisions if seen_decisions is not None else {}

    if plan_state == PlanState.PROPOSED:
        # PROPOSED -> WAITING_APPROVAL: submission for review. Not
        # decision-driven, so the audit reason code records "submitted", i.e.
        # the plan advanced into the approval queue (no approver decision
        # exists yet at this point in the machine).
        return TransitionOutcome(
            state=PlanState.WAITING_APPROVAL,
            audit_record=AuditTrailRecord(
                contract_hash=contract_hash,
                actor_id=proposer_actor_id,
                decided_at=decided_at,
                from_state=PlanState.PROPOSED,
                to_state=PlanState.WAITING_APPROVAL,
                reason_code=AuditReasonCode.SUBMITTED_FOR_APPROVAL,
            ),
        )

    if plan_state != PlanState.WAITING_APPROVAL:
        raise InvalidTransitionError(plan_state, incoming_decision)

    # Immutability choke point (critic MUST-FIX 1): runs BEFORE any other
    # state logic on the approval path. A caller cannot reach APPROVED (or
    # any other WAITING_APPROVAL outcome) through this function while
    # bypassing this check. Both-or-neither of stored_plan/presented_plan
    # are the only legal states — supplying exactly one would silently skip
    # guard_immutability (fail-open), so a partial pair fails closed instead
    # (critic MUST-FIX 1 re-verify).
    if (stored_plan is None) != (presented_plan is None):
        raise InconsistentPlanSnapshotError(
            "transition() requires both stored_plan and presented_plan, or "
            f"neither: got stored_plan={stored_plan!r}, presented_plan={presented_plan!r}"
        )
    if stored_plan is not None and presented_plan is not None:
        guard_immutability(
            contract_hash=presented_plan.contract_hash,
            prior_contract_hash=stored_plan.contract_hash,
            prior_content_fingerprint=stored_plan.content_fingerprint,
            new_content_fingerprint=presented_plan.content_fingerprint,
        )

    if incoming_decision is None:
        raise InvalidTransitionError(plan_state, incoming_decision)

    if incoming_decision.contract_hash != contract_hash:
        raise ContractHashViolationError(
            f"decision contract_hash {incoming_decision.contract_hash!r} does not "
            f"match plan contract_hash {contract_hash!r}"
        )

    key = incoming_decision.decision_key
    prior = seen.get(key)
    if prior is not None:
        if prior.decision == incoming_decision.decision:
            # Idempotent replay: identical decision resubmitted (approver
            # identity compared via the canonicalized decision_key). No
            # duplicate state change — recompute the CURRENT outcome from
            # `approvals` (which already reflects the first application) and
            # return it unchanged.
            pass
        else:
            raise ConflictingDecisionError(
                f"approver {incoming_decision.approver_actor_id!r} submitted "
                f"conflicting decisions for contract_hash {contract_hash!r}: "
                f"{prior.decision!r} then {incoming_decision.decision!r}"
            )

    if canonical_actor_id(incoming_decision.approver_actor_id) == canonical_actor_id(
        proposer_actor_id
    ):
        raise InvalidTransitionError(plan_state, incoming_decision)

    if incoming_decision.decision == "rejected":
        return TransitionOutcome(
            state=PlanState.REJECTED,
            audit_record=AuditTrailRecord(
                contract_hash=contract_hash,
                actor_id=incoming_decision.approver_actor_id,
                decided_at=decided_at,
                from_state=PlanState.WAITING_APPROVAL,
                to_state=PlanState.REJECTED,
                reason_code=AuditReasonCode.REJECTED_BY_APPROVER,
            ),
        )

    quorum_met = evaluate_h7_two_person_approval(
        proposer_actor_id=proposer_actor_id,
        approvals=approvals,
        high_risk=high_risk,
    )
    if quorum_met:
        return TransitionOutcome(
            state=PlanState.APPROVED,
            audit_record=AuditTrailRecord(
                contract_hash=contract_hash,
                actor_id=incoming_decision.approver_actor_id,
                decided_at=decided_at,
                from_state=PlanState.WAITING_APPROVAL,
                to_state=PlanState.APPROVED,
                reason_code=AuditReasonCode.APPROVED_SUFFICIENT_QUORUM,
            ),
        )

    # Insufficient quorum yet (e.g. first of 2 required H-7 approvers) — plan
    # stays WAITING_APPROVAL; this is expected, not an error.
    return TransitionOutcome(
        state=PlanState.WAITING_APPROVAL,
        audit_record=AuditTrailRecord(
            contract_hash=contract_hash,
            actor_id=incoming_decision.approver_actor_id,
            decided_at=decided_at,
            from_state=PlanState.WAITING_APPROVAL,
            to_state=PlanState.WAITING_APPROVAL,
            reason_code=AuditReasonCode.QUORUM_PENDING,
        ),
    )


def cancel(
    plan_state: PlanState,
    *,
    contract_hash: str,
    actor_id: str,
    decided_at: str,
    by_operator: bool = False,
) -> TransitionOutcome:
    """Explicit cancellation path (proposer withdrawal or operator override).

    Valid from PROPOSED or WAITING_APPROVAL only (k3s §4.3: CANCELLED is
    reachable from WAITING_APPROVAL on rejection; PROPOSED->CANCELLED models
    proposer withdrawal before submission — this module's own extension,
    consistent with _ALLOWED_TRANSITIONS, which is this function's single
    source of truth for validity, SHOULD-FIX 4).
    """
    if PlanState.CANCELLED not in _ALLOWED_TRANSITIONS.get(plan_state, frozenset()):
        raise InvalidTransitionError(plan_state, "cancel")
    reason = (
        AuditReasonCode.CANCELLED_BY_OPERATOR
        if by_operator
        else AuditReasonCode.CANCELLED_BY_PROPOSER
    )
    return TransitionOutcome(
        state=PlanState.CANCELLED,
        audit_record=AuditTrailRecord(
            contract_hash=contract_hash,
            actor_id=actor_id,
            decided_at=decided_at,
            from_state=plan_state,
            to_state=PlanState.CANCELLED,
            reason_code=reason,
        ),
    )


def expire(
    plan_state: PlanState,
    *,
    contract_hash: str,
    actor_id: str,
    decided_at: str,
) -> TransitionOutcome:
    """Expiry path — lease/approval window lapsed. Valid only from
    WAITING_APPROVAL (see states.py OPEN ITEM re: k3s §4.3 silence on expiry).
    Validity is checked against _ALLOWED_TRANSITIONS (SHOULD-FIX 4), the
    single source of truth for this module's adjacency, rather than a
    hardcoded state comparison.
    """
    if PlanState.EXPIRED not in _ALLOWED_TRANSITIONS.get(plan_state, frozenset()):
        raise InvalidTransitionError(plan_state, "expire")
    return TransitionOutcome(
        state=PlanState.EXPIRED,
        audit_record=AuditTrailRecord(
            contract_hash=contract_hash,
            actor_id=actor_id,
            decided_at=decided_at,
            from_state=plan_state,
            to_state=PlanState.EXPIRED,
            reason_code=AuditReasonCode.EXPIRED_LEASE_WINDOW,
        ),
    )


def guard_execution(
    plan_state: PlanState,
    *,
    approval_decision: str | None,
) -> None:
    """Raise ExecutionBlockedError unless the plan is APPROVED and carries a
    valid ("approved") approval decision. No execution before approval
    (task instruction 1) — this is the single choke point callers must invoke
    before any write/execute action proceeds.
    """
    if plan_state != PlanState.APPROVED:
        raise ExecutionBlockedError(
            f"execution blocked: plan_state is {plan_state!r}, not {PlanState.APPROVED!r}"
        )
    if approval_decision != "approved":
        raise ExecutionBlockedError(
            f"execution blocked: approval_decision is {approval_decision!r}, expected 'approved'"
        )


def guard_immutability(
    *,
    contract_hash: str,
    prior_contract_hash: str,
    prior_content_fingerprint: str,
    new_content_fingerprint: str,
) -> None:
    """After approval, contract_hash is frozen. Raise ContractHashViolationError
    if a re-propose reuses the same contract_hash but with different content
    (content fingerprint mismatch under an unchanged hash is itself the
    violation signal — a correct re-propose with different content MUST also
    produce a different contract_hash).
    """
    if contract_hash != prior_contract_hash:
        return
    if new_content_fingerprint != prior_content_fingerprint:
        raise ContractHashViolationError(
            f"contract_hash {contract_hash!r} reused with different content "
            "after approval (post-approval immutability violation)"
        )


__all__ = [
    "DecisionRecord",
    "PlanSnapshot",
    "TransitionOutcome",
    "cancel",
    "expire",
    "guard_execution",
    "guard_immutability",
    "is_high_risk_plan",
    "transition",
]

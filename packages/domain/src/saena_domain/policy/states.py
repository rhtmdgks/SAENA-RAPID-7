"""ChangePlan approval-lifecycle state enum.

Authority: k3s spec §4.3 defines the run-level state machine
(INTAKE -> DISCOVERY -> PLAN_DRAFT -> WAITING_APPROVAL -> EXECUTING | CANCELLED
-> ...). Neither `change-plan.schema.json` nor `approval-decision.schema.json`
carries an explicit lifecycle "status" field on the ChangePlan contract itself
(the contract is a point-in-time, closed, signed document — see change-plan
schema $comment on `contract_hash` self-reference avoidance). This module
therefore models the *approval sub-machine* of k3s §4.3 (the PLAN_DRAFT ..
EXECUTING/CANCELLED span that this policy module is responsible for gating)
as an explicit, testable state enum, plus two states — EXPIRED and REJECTED —
that k3s §4.3 does not name as distinct terminal states but that ADR-0003 and
security-model.md require as first-class outcomes (ADR-0003 "거부 시 여기서
종료"; a lease/approval window can also lapse without an explicit reject).

Mapping to k3s §4.3 vocabulary:
    PROPOSED         ~= PLAN_DRAFT (Action Contract authored, not yet submitted
                        for approval)
    WAITING_APPROVAL ==  WAITING_APPROVAL (k3s §4.3 verbatim)
    APPROVED         ~= the state that authorizes the EXECUTING transition
                        (ADR-0003: Policy Gate pre-verification recorded,
                        Temporal signal not yet necessarily sent — this module
                        stops at "approved, execution may proceed", it does not
                        model EXECUTING/QUALITY_GATE/... which belong to the
                        Temporal workflow, out of this patch unit's scope)
    REJECTED         ==  CANCELLED (k3s §4.3 labels the WAITING_APPROVAL
                        rejection target CANCELLED; ApprovalDecision.decision
                        uses the literal string "rejected" (schema enum) —
                        this module names the state REJECTED to stay aligned
                        with the contract's own vocabulary and treats it as
                        the CANCELLED-by-rejection case)
    CANCELLED        ==  CANCELLED (k3s §4.3) reached by proposer/operator
                        withdrawal rather than approver rejection
    EXPIRED          -- not named in k3s §4.3; added because a lease/approval
                        window (H-7 "per-patch-unit lease") must be able to
                        lapse. OPEN ITEM: k3s §4.3 does not define an expiry
                        transition; this module treats EXPIRED as reachable
                        only from WAITING_APPROVAL, mirroring CANCELLED.

OPEN ITEM: whether EXPIRED/CANCELLED are truly distinct from REJECTED at the
audit-ledger level is not specified by the read specs; this module keeps them
distinct because they have different actors/reason codes (see audit.py).
"""

from __future__ import annotations

from enum import StrEnum


class PlanState(StrEnum):
    """Approval-lifecycle states for a ChangePlan (Action Contract)."""

    PROPOSED = "proposed"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


TERMINAL_STATES: frozenset[PlanState] = frozenset(
    {PlanState.APPROVED, PlanState.REJECTED, PlanState.EXPIRED, PlanState.CANCELLED}
)

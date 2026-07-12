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

OPEN ITEM (SHOULD-FIX 6, strengthened per critic review): k3s §4.3's
state-diagram literally has exactly TWO terminal outcomes reachable from
WAITING_APPROVAL — EXECUTING (via `approved`) and CANCELLED (via
`rejected`). This module's PlanState deliberately WIDENS that second,
single k3s-level CANCELLED outcome into three distinct states — REJECTED,
EXPIRED, CANCELLED — because they have different actors, triggers, and audit
reason codes (see audit.py AuditReasonCode) that a policy/audit consumer
needs to distinguish. This is an intentional implementation choice, not a
literal 1:1 rendering of the k3s diagram: at the k3s event/state-diagram
level, REJECTED, EXPIRED, and CANCELLED here all COLLAPSE onto the single
k3s `CANCELLED` node. Any component that maps this module's PlanState back
onto the k3s §4.3 vocabulary (e.g. run-level status reporting, Temporal
workflow state) must perform that many-to-one collapse explicitly. This
widening is NOT itself a change to k3s §4.3 or any ADR — docs/specs and
docs/decisions were not edited to accommodate it — and is flagged here for
human follow-up (should k3s §4.3 itself be revised to name these three
outcomes explicitly, or should this module's three states instead be
represented as CANCELLED + a separate reason-code-only distinction?). Do not
resolve this by editing docs/specs/** or docs/decisions/ADR-*.md status.
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

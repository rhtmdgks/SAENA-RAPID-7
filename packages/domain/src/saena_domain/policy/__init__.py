"""saena_domain.policy — ChangePlan / ApprovalDecision state machine + H-3/H-7 policy gate.

Source specification references (READ ONLY basis for this module):
- docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md §4.3 (run/plan state machine)
- docs/decisions/ADR-0003-approval-transition-authority-path.md (approval authority path)
- docs/architecture/security-model.md H-3 (evidence anchoring, scope/diff limits),
  H-7 (two-person approval, per-patch-unit lease)
- docs/architecture/agent-authority-boundaries.md
- docs/architecture/contract-catalog.md (ChangePlan/ApprovalDecision rows)
- packages/contracts/json-schema/domain/change-plan/v1/change-plan.schema.json
- packages/contracts/json-schema/domain/approval-decision/v1/approval-decision.schema.json
"""

from __future__ import annotations

from saena_domain.policy.audit import AuditReasonCode, AuditTrailRecord
from saena_domain.policy.errors import (
    ConflictingDecisionError,
    ContractHashViolationError,
    ExecutionBlockedError,
    InconsistentPlanSnapshotError,
    InvalidTransitionError,
    PolicyViolationError,
)
from saena_domain.policy.evidence import evaluate_h3_evidence_policy
from saena_domain.policy.identity import canonical_actor_id
from saena_domain.policy.lease import PatchUnitLease, issue_lease
from saena_domain.policy.states import PlanState
from saena_domain.policy.transitions import (
    DecisionRecord,
    PlanSnapshot,
    TransitionOutcome,
    guard_execution,
    guard_immutability,
    is_high_risk_plan,
    transition,
)
from saena_domain.policy.two_person import evaluate_h7_two_person_approval

__all__ = [
    "AuditReasonCode",
    "AuditTrailRecord",
    "ConflictingDecisionError",
    "ContractHashViolationError",
    "DecisionRecord",
    "ExecutionBlockedError",
    "InconsistentPlanSnapshotError",
    "InvalidTransitionError",
    "PatchUnitLease",
    "PlanSnapshot",
    "PlanState",
    "PolicyViolationError",
    "TransitionOutcome",
    "canonical_actor_id",
    "evaluate_h3_evidence_policy",
    "evaluate_h7_two_person_approval",
    "guard_execution",
    "guard_immutability",
    "is_high_risk_plan",
    "issue_lease",
    "transition",
]

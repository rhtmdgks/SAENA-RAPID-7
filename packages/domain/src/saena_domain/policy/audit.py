"""Plain audit-trail record descriptors fed to the audit ledger by services.

This module produces value objects only — it does not write to any ledger.
contract-catalog.md AuditEvent ownership/append semantics are out of this
patch unit's exclusive-write scope (packages/domain/src/saena_domain/policy
and authz only); services wire these descriptors to the actual audit-ledger
append API.

NO PII beyond actor_id (task spec instruction 5) — reason is a closed code,
not free text, to avoid PII/secret leakage into the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from saena_domain.policy.states import PlanState


class AuditReasonCode(StrEnum):
    """Closed reason-code set for policy-driven state transitions.

    Closed (not free text) per task instruction 5 ("NO PII beyond actor_id") —
    a free-text reason field is a PII/secret-leakage vector into the audit
    trail; this module only allows this fixed vocabulary.
    """

    SUBMITTED_FOR_APPROVAL = "submitted_for_approval"
    APPROVED_SUFFICIENT_QUORUM = "approved_sufficient_quorum"
    QUORUM_PENDING = "quorum_pending"
    # w2-24 (Wave 2 critic follow-up, audit-truthfulness bug): a policy-gate
    # DENIAL (ADR-0003 step (1), evaluated BEFORE `transition()`/quorum ever
    # runs) is a semantically distinct event from "not enough approvers have
    # signed off yet" (QUORUM_PENDING, a `transition()`-internal outcome).
    # Services must map a gate deny onto THIS member, never onto
    # QUORUM_PENDING — conflating the two would make the audit trail claim a
    # decision was still awaiting quorum when it was actually rejected by the
    # gate outright.
    GATE_DENIED = "gate_denied"
    REJECTED_BY_APPROVER = "rejected_by_approver"
    REJECTED_SELF_APPROVAL = "rejected_self_approval"
    REJECTED_DUPLICATE_APPROVER = "rejected_duplicate_approver"
    REJECTED_H3_EVIDENCE_MISSING = "rejected_h3_evidence_missing"
    REJECTED_H3_SCOPE_ESCAPE = "rejected_h3_scope_escape"
    REJECTED_H3_BUDGET_EXCEEDED = "rejected_h3_budget_exceeded"
    EXPIRED_LEASE_WINDOW = "expired_lease_window"
    CANCELLED_BY_PROPOSER = "cancelled_by_proposer"
    CANCELLED_BY_OPERATOR = "cancelled_by_operator"
    CONTRACT_HASH_VIOLATION = "contract_hash_violation"
    CONFLICTING_DECISION = "conflicting_decision"


@dataclass(frozen=True, slots=True)
class AuditTrailRecord:
    """Plain descriptor of a policy-driven decision, for the audit ledger.

    Fields deliberately mirror task instruction 5: decision, actor_id,
    timestamp, reason code. `from_state`/`to_state` are included because the
    consuming audit-ledger schema needs the transition shape, not just the
    outcome; no PII beyond actor_id is carried anywhere in this record.
    """

    contract_hash: str
    actor_id: str
    decided_at: str
    from_state: PlanState
    to_state: PlanState
    reason_code: AuditReasonCode

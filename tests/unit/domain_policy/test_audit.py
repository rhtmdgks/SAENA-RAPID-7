"""Audit-trail record descriptor — no PII beyond actor_id, closed reason codes."""

from __future__ import annotations

import dataclasses

from saena_domain.policy.audit import AuditReasonCode, AuditTrailRecord
from saena_domain.policy.states import PlanState


def test_audit_trail_record_fields_are_pii_minimal() -> None:
    record = AuditTrailRecord(
        contract_hash="sha256:" + "a" * 64,
        actor_id="actor-approver-0001",
        decided_at="2026-07-12T10:00:00Z",
        from_state=PlanState.WAITING_APPROVAL,
        to_state=PlanState.APPROVED,
        reason_code=AuditReasonCode.APPROVED_SUFFICIENT_QUORUM,
    )
    field_names = {f.name for f in dataclasses.fields(record)}
    # Only actor_id may carry any actor-identifying data; no free-text/PII
    # fields (e.g. "reason", "note", "email") are present.
    assert field_names == {
        "contract_hash",
        "actor_id",
        "decided_at",
        "from_state",
        "to_state",
        "reason_code",
    }


def test_audit_trail_record_is_immutable() -> None:
    record = AuditTrailRecord(
        contract_hash="sha256:" + "a" * 64,
        actor_id="actor-approver-0001",
        decided_at="2026-07-12T10:00:00Z",
        from_state=PlanState.WAITING_APPROVAL,
        to_state=PlanState.APPROVED,
        reason_code=AuditReasonCode.APPROVED_SUFFICIENT_QUORUM,
    )
    import pytest

    with pytest.raises(AttributeError):
        record.actor_id = "someone-else"  # type: ignore[misc]


def test_reason_code_is_closed_enum_not_free_text() -> None:
    values = {code.value for code in AuditReasonCode}
    assert "approved_sufficient_quorum" in values
    assert "quorum_pending" in values
    assert "gate_denied" in values
    assert "rejected_by_approver" in values
    assert "rejected_self_approval" in values
    assert "rejected_duplicate_approver" in values
    assert "rejected_h3_evidence_missing" in values
    assert "rejected_h3_scope_escape" in values
    assert "rejected_h3_budget_exceeded" in values
    assert "expired_lease_window" in values
    assert "cancelled_by_proposer" in values
    assert "cancelled_by_operator" in values
    assert "contract_hash_violation" in values
    assert "conflicting_decision" in values


def test_gate_denied_is_distinct_from_quorum_pending() -> None:
    # w2-24 (Wave 2 critic follow-up, audit-truthfulness bug): GATE_DENIED
    # ("the policy gate denied this decision outright") must be a member
    # distinct from QUORUM_PENDING ("not enough approvers have signed off
    # yet") — a service that conflates the two would misreport a gate
    # rejection as a still-pending approval in the audit trail.
    assert AuditReasonCode.GATE_DENIED != AuditReasonCode.QUORUM_PENDING
    assert AuditReasonCode.GATE_DENIED.value == "gate_denied"

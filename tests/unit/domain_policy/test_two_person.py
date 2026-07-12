"""H-7 evaluate_h7_two_person_approval unit coverage (direct, isolated)."""

from __future__ import annotations

from saena_domain.policy.two_person import ApproverRecord, evaluate_h7_two_person_approval

PROPOSER = "actor-proposer-0001"
A1 = "actor-approver-0001"
A2 = "actor-approver-0002"


def test_low_risk_single_distinct_approver_sufficient() -> None:
    assert evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(A1, "approved"),),
        high_risk=False,
    )


def test_high_risk_single_approver_insufficient() -> None:
    assert not evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(A1, "approved"),),
        high_risk=True,
    )


def test_high_risk_two_distinct_approvers_sufficient() -> None:
    assert evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(A1, "approved"), ApproverRecord(A2, "approved")),
        high_risk=True,
    )


def test_high_risk_same_approver_twice_insufficient() -> None:
    assert not evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(A1, "approved"), ApproverRecord(A1, "approved")),
        high_risk=True,
    )


def test_proposer_cannot_count_as_approver_low_risk() -> None:
    assert not evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(PROPOSER, "approved"),),
        high_risk=False,
    )


def test_proposer_cannot_count_as_approver_high_risk() -> None:
    assert not evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(
            ApproverRecord(PROPOSER, "approved"),
            ApproverRecord(A1, "approved"),
        ),
        high_risk=True,
    )


def test_rejected_decisions_do_not_count_toward_quorum() -> None:
    assert not evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(A1, "rejected"),),
        high_risk=False,
    )


def test_no_approvals_insufficient() -> None:
    assert not evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER, approvals=(), high_risk=False
    )

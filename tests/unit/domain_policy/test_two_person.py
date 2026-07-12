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


# --- MUST-FIX 2: actor_id canonicalization ----------------------------------


def test_case_variant_same_approver_does_not_double_count() -> None:
    assert not evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(
            ApproverRecord("Actor-Approver-0001", "approved"),
            ApproverRecord("actor-approver-0001", "approved"),
        ),
        high_risk=True,
    )


def test_whitespace_variant_same_approver_does_not_double_count() -> None:
    assert not evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(
            ApproverRecord(" actor-approver-0001", "approved"),
            ApproverRecord("actor-approver-0001 ", "approved"),
        ),
        high_risk=True,
    )


def test_proposer_case_variant_cannot_count_as_approver() -> None:
    assert not evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(PROPOSER.upper(), "approved"),),
        high_risk=False,
    )


def test_proposer_whitespace_variant_cannot_count_as_approver() -> None:
    assert not evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(f"  {PROPOSER}  ", "approved"),),
        high_risk=False,
    )


def test_case_and_whitespace_variant_distinct_approvers_still_satisfy_high_risk() -> None:
    # Two GENUINELY distinct approvers, each submitted with incidental
    # whitespace/case noise, must still satisfy the 2-distinct requirement —
    # canonicalization must not over-collapse different identities.
    assert evaluate_h7_two_person_approval(
        proposer_actor_id=PROPOSER,
        approvals=(
            ApproverRecord(" Actor-Approver-0001 ", "approved"),
            ApproverRecord("ACTOR-APPROVER-0002", "approved"),
        ),
        high_risk=True,
    )

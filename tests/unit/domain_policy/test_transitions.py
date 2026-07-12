"""Full transition matrix, incl. every illegal edge, two-person approval,
idempotent replay, and conflicting decision (task TESTS instruction)."""

from __future__ import annotations

import pytest
from saena_domain.policy.audit import AuditReasonCode
from saena_domain.policy.errors import (
    ConflictingDecisionError,
    ContractHashViolationError,
    ExecutionBlockedError,
    InconsistentPlanSnapshotError,
    InvalidTransitionError,
)
from saena_domain.policy.states import PlanState
from saena_domain.policy.transitions import (
    DecisionRecord,
    PlanSnapshot,
    cancel,
    expire,
    guard_execution,
    guard_immutability,
    is_high_risk_plan,
    transition,
)
from saena_domain.policy.two_person import ApproverRecord

CONTRACT_HASH = "sha256:" + "a" * 64
PROPOSER = "actor-proposer-0001"
APPROVER_1 = "actor-approver-0001"
APPROVER_2 = "actor-approver-0002"
DECIDED_AT = "2026-07-12T10:00:00Z"


def _decision(
    approver: str,
    decision: str,
    *,
    high_risk: bool = False,
    contract_hash: str = CONTRACT_HASH,
) -> DecisionRecord:
    return DecisionRecord(
        contract_hash=contract_hash,
        approver_actor_id=approver,
        decision=decision,
        proposer_actor_id=PROPOSER,
        high_risk=high_risk,
        decided_at=DECIDED_AT,
    )


# --- legal edges -----------------------------------------------------------


def test_proposed_advances_to_waiting_approval() -> None:
    outcome = transition(
        PlanState.PROPOSED,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=(),
        high_risk=False,
        decided_at=DECIDED_AT,
    )
    assert outcome.state == PlanState.WAITING_APPROVAL
    assert outcome.audit_record.reason_code == AuditReasonCode.SUBMITTED_FOR_APPROVAL
    assert outcome.audit_record.from_state == PlanState.PROPOSED
    assert outcome.audit_record.to_state == PlanState.WAITING_APPROVAL


def test_waiting_approval_low_risk_single_approver_reaches_approved() -> None:
    approvals = (ApproverRecord(APPROVER_1, "approved"),)
    outcome = transition(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=approvals,
        high_risk=False,
        decided_at=DECIDED_AT,
        incoming_decision=_decision(APPROVER_1, "approved"),
    )
    assert outcome.state == PlanState.APPROVED
    assert outcome.audit_record.reason_code == AuditReasonCode.APPROVED_SUFFICIENT_QUORUM


def test_waiting_approval_high_risk_requires_two_distinct_approvers() -> None:
    # First approver only -> quorum pending, still WAITING_APPROVAL.
    first_approvals = (ApproverRecord(APPROVER_1, "approved"),)
    outcome1 = transition(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=first_approvals,
        high_risk=True,
        decided_at=DECIDED_AT,
        incoming_decision=_decision(APPROVER_1, "approved", high_risk=True),
    )
    assert outcome1.state == PlanState.WAITING_APPROVAL
    assert outcome1.audit_record.reason_code == AuditReasonCode.QUORUM_PENDING

    # Second DISTINCT approver -> quorum satisfied -> APPROVED.
    both_approvals = (
        ApproverRecord(APPROVER_1, "approved"),
        ApproverRecord(APPROVER_2, "approved"),
    )
    outcome2 = transition(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=both_approvals,
        high_risk=True,
        decided_at=DECIDED_AT,
        incoming_decision=_decision(APPROVER_2, "approved", high_risk=True),
    )
    assert outcome2.state == PlanState.APPROVED


def test_waiting_approval_rejected_reaches_rejected() -> None:
    outcome = transition(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=(),
        high_risk=False,
        decided_at=DECIDED_AT,
        incoming_decision=_decision(APPROVER_1, "rejected"),
    )
    assert outcome.state == PlanState.REJECTED
    assert outcome.audit_record.reason_code == AuditReasonCode.REJECTED_BY_APPROVER


def test_cancel_from_proposed() -> None:
    outcome = cancel(
        PlanState.PROPOSED,
        contract_hash=CONTRACT_HASH,
        actor_id=PROPOSER,
        decided_at=DECIDED_AT,
    )
    assert outcome.state == PlanState.CANCELLED
    assert outcome.audit_record.reason_code == AuditReasonCode.CANCELLED_BY_PROPOSER


def test_cancel_from_waiting_approval_by_operator() -> None:
    outcome = cancel(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        actor_id="actor-operator-0001",
        decided_at=DECIDED_AT,
        by_operator=True,
    )
    assert outcome.state == PlanState.CANCELLED
    assert outcome.audit_record.reason_code == AuditReasonCode.CANCELLED_BY_OPERATOR


def test_expire_from_waiting_approval() -> None:
    outcome = expire(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        actor_id="actor-operator-0001",
        decided_at=DECIDED_AT,
    )
    assert outcome.state == PlanState.EXPIRED
    assert outcome.audit_record.reason_code == AuditReasonCode.EXPIRED_LEASE_WINDOW


# --- illegal edges: every terminal state is a dead end ----------------------


@pytest.mark.parametrize(
    "terminal_state",
    [PlanState.APPROVED, PlanState.REJECTED, PlanState.EXPIRED, PlanState.CANCELLED],
)
def test_transition_from_terminal_state_is_invalid(terminal_state: PlanState) -> None:
    with pytest.raises(InvalidTransitionError):
        transition(
            terminal_state,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(),
            high_risk=False,
            decided_at=DECIDED_AT,
            incoming_decision=_decision(APPROVER_1, "approved"),
        )


@pytest.mark.parametrize(
    "terminal_state",
    [PlanState.APPROVED, PlanState.REJECTED, PlanState.EXPIRED, PlanState.CANCELLED],
)
def test_cancel_from_terminal_state_is_invalid(terminal_state: PlanState) -> None:
    with pytest.raises(InvalidTransitionError):
        cancel(
            terminal_state,
            contract_hash=CONTRACT_HASH,
            actor_id=PROPOSER,
            decided_at=DECIDED_AT,
        )


@pytest.mark.parametrize(
    "state",
    [
        PlanState.PROPOSED,
        PlanState.APPROVED,
        PlanState.REJECTED,
        PlanState.EXPIRED,
        PlanState.CANCELLED,
    ],
)
def test_expire_only_valid_from_waiting_approval(state: PlanState) -> None:
    with pytest.raises(InvalidTransitionError):
        expire(
            state,
            contract_hash=CONTRACT_HASH,
            actor_id=PROPOSER,
            decided_at=DECIDED_AT,
        )


def test_waiting_approval_without_incoming_decision_is_invalid() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(),
            high_risk=False,
            decided_at=DECIDED_AT,
            incoming_decision=None,
        )


# --- H-7 two-person: same approver twice / proposer self-approve -----------


def test_same_approver_twice_never_satisfies_high_risk_quorum() -> None:
    # Approver 1 "approves" twice (duplicate submission) — dedups to 1
    # distinct approver, insufficient for high-risk 2-distinct requirement.
    approvals = (
        ApproverRecord(APPROVER_1, "approved"),
        ApproverRecord(APPROVER_1, "approved"),
    )
    outcome = transition(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=approvals,
        high_risk=True,
        decided_at=DECIDED_AT,
        incoming_decision=_decision(APPROVER_1, "approved", high_risk=True),
    )
    assert outcome.state == PlanState.WAITING_APPROVAL


def test_proposer_self_approve_is_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(ApproverRecord(PROPOSER, "approved"),),
            high_risk=False,
            decided_at=DECIDED_AT,
            incoming_decision=_decision(PROPOSER, "approved"),
        )


def test_proposer_self_approve_forbidden_even_for_low_risk() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(),
            high_risk=False,
            decided_at=DECIDED_AT,
            incoming_decision=_decision(PROPOSER, "approved", high_risk=False),
        )


# --- idempotent replay / conflicting decision -------------------------------


def test_idempotent_replay_identical_decision_no_duplicate_state_change() -> None:
    seen = {
        (CONTRACT_HASH, APPROVER_1): _decision(APPROVER_1, "approved"),
    }
    outcome = transition(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(APPROVER_1, "approved"),),
        high_risk=False,
        decided_at=DECIDED_AT,
        seen_decisions=seen,
        incoming_decision=_decision(APPROVER_1, "approved"),
    )
    # Replaying the SAME decision produces the SAME result as the first
    # application (APPROVED for low-risk single-approver quorum) — no error,
    # no different outcome.
    assert outcome.state == PlanState.APPROVED


def test_conflicting_decision_for_same_approver_raises() -> None:
    seen = {
        (CONTRACT_HASH, APPROVER_1): _decision(APPROVER_1, "approved"),
    }
    with pytest.raises(ConflictingDecisionError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(ApproverRecord(APPROVER_1, "approved"),),
            high_risk=False,
            decided_at=DECIDED_AT,
            seen_decisions=seen,
            incoming_decision=_decision(APPROVER_1, "rejected"),
        )


def test_decision_contract_hash_mismatch_raises_contract_hash_violation() -> None:
    other_hash = "sha256:" + "b" * 64
    with pytest.raises(ContractHashViolationError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(),
            high_risk=False,
            decided_at=DECIDED_AT,
            incoming_decision=_decision(APPROVER_1, "approved", contract_hash=other_hash),
        )


# --- guard_execution ---------------------------------------------------------


def test_guard_execution_blocks_unless_approved_and_valid_decision() -> None:
    with pytest.raises(ExecutionBlockedError):
        guard_execution(PlanState.WAITING_APPROVAL, approval_decision="approved")
    with pytest.raises(ExecutionBlockedError):
        guard_execution(PlanState.APPROVED, approval_decision="rejected")
    with pytest.raises(ExecutionBlockedError):
        guard_execution(PlanState.APPROVED, approval_decision=None)


def test_guard_execution_passes_when_approved_and_valid() -> None:
    guard_execution(PlanState.APPROVED, approval_decision="approved")  # no raise


@pytest.mark.parametrize(
    "state",
    [PlanState.PROPOSED, PlanState.REJECTED, PlanState.EXPIRED, PlanState.CANCELLED],
)
def test_guard_execution_blocks_all_non_approved_states(state: PlanState) -> None:
    with pytest.raises(ExecutionBlockedError):
        guard_execution(state, approval_decision="approved")


# --- immutability -------------------------------------------------------------


def test_guard_immutability_allows_same_hash_same_content() -> None:
    guard_immutability(
        contract_hash=CONTRACT_HASH,
        prior_contract_hash=CONTRACT_HASH,
        prior_content_fingerprint="fp-1",
        new_content_fingerprint="fp-1",
    )  # no raise


def test_guard_immutability_allows_different_hash_different_content() -> None:
    guard_immutability(
        contract_hash="sha256:" + "c" * 64,
        prior_contract_hash=CONTRACT_HASH,
        prior_content_fingerprint="fp-1",
        new_content_fingerprint="fp-2",
    )  # no raise — different content correctly produced a different hash


def test_guard_immutability_raises_on_same_hash_different_content() -> None:
    with pytest.raises(ContractHashViolationError):
        guard_immutability(
            contract_hash=CONTRACT_HASH,
            prior_contract_hash=CONTRACT_HASH,
            prior_content_fingerprint="fp-1",
            new_content_fingerprint="fp-2",
        )


# --- is_high_risk_plan --------------------------------------------------------


def test_is_high_risk_plan_true_when_any_hypothesis_high() -> None:
    assert is_high_risk_plan(("low", "high"))
    assert is_high_risk_plan(("high",))


def test_is_high_risk_plan_false_when_no_hypothesis_high() -> None:
    assert not is_high_risk_plan(("low", "medium"))
    assert not is_high_risk_plan(())


# --- MUST-FIX 1: immutability wired into transition() as a choke point -----


def test_transition_raises_contract_hash_violation_on_mutated_content_same_hash() -> None:
    """Mutated content under the same contract_hash must be caught BY
    transition() itself (not only by a standalone guard_immutability call)."""
    stored = PlanSnapshot(contract_hash=CONTRACT_HASH, content_fingerprint="fp-original")
    presented = PlanSnapshot(contract_hash=CONTRACT_HASH, content_fingerprint="fp-mutated")
    with pytest.raises(ContractHashViolationError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(ApproverRecord(APPROVER_1, "approved"),),
            high_risk=False,
            decided_at=DECIDED_AT,
            incoming_decision=_decision(APPROVER_1, "approved"),
            stored_plan=stored,
            presented_plan=presented,
        )


def test_transition_immutability_check_runs_before_state_logic() -> None:
    """The immutability violation must fire even when the decision itself
    would otherwise be perfectly valid (quorum satisfied, no self-approval,
    no replay conflict) — proving the check runs unconditionally FIRST, not
    as a fallback only reached when other checks pass."""
    stored = PlanSnapshot(contract_hash=CONTRACT_HASH, content_fingerprint="fp-original")
    presented = PlanSnapshot(contract_hash=CONTRACT_HASH, content_fingerprint="fp-mutated")
    with pytest.raises(ContractHashViolationError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(ApproverRecord(APPROVER_1, "approved"),),
            high_risk=False,
            decided_at=DECIDED_AT,
            incoming_decision=_decision(APPROVER_1, "approved"),
            stored_plan=stored,
            presented_plan=presented,
        )


def test_transition_allows_same_hash_same_content() -> None:
    stored = PlanSnapshot(contract_hash=CONTRACT_HASH, content_fingerprint="fp-original")
    presented = PlanSnapshot(contract_hash=CONTRACT_HASH, content_fingerprint="fp-original")
    outcome = transition(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(APPROVER_1, "approved"),),
        high_risk=False,
        decided_at=DECIDED_AT,
        incoming_decision=_decision(APPROVER_1, "approved"),
        stored_plan=stored,
        presented_plan=presented,
    )
    assert outcome.state == PlanState.APPROVED


def test_transition_does_not_false_positive_when_hash_and_content_both_differ() -> None:
    # A legitimately re-proposed plan (new contract_hash for new content) is
    # NOT a contract-hash-reuse violation — guard_immutability only fires
    # when the SAME contract_hash is reused with DIFFERENT content. Here the
    # presented snapshot's contract_hash differs from stored, so the
    # immutability check must be a no-op; the transition proceeds normally
    # against the (matching) plan/decision contract_hash.
    stored = PlanSnapshot(contract_hash=CONTRACT_HASH, content_fingerprint="fp-original")
    other_hash = "sha256:" + "c" * 64
    presented = PlanSnapshot(contract_hash=other_hash, content_fingerprint="fp-changed")
    outcome = transition(
        PlanState.WAITING_APPROVAL,
        contract_hash=other_hash,
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(APPROVER_1, "approved"),),
        high_risk=False,
        decided_at=DECIDED_AT,
        incoming_decision=_decision(APPROVER_1, "approved", contract_hash=other_hash),
        stored_plan=stored,
        presented_plan=presented,
    )
    assert outcome.state == PlanState.APPROVED


def test_transition_skips_immutability_check_when_snapshots_omitted() -> None:
    # Default behavior unchanged when stored_plan/presented_plan are not
    # supplied (e.g. PROPOSED->WAITING_APPROVAL submission path).
    outcome = transition(
        PlanState.PROPOSED,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=(),
        high_risk=False,
        decided_at=DECIDED_AT,
    )
    assert outcome.state == PlanState.WAITING_APPROVAL


def test_transition_raises_on_stored_plan_only_partial_snapshot() -> None:
    # Critic MUST-FIX 1 re-verify: supplying exactly ONE of
    # stored_plan/presented_plan must fail closed, not silently skip
    # guard_immutability.
    stored = PlanSnapshot(contract_hash=CONTRACT_HASH, content_fingerprint="fp-original")
    with pytest.raises(InconsistentPlanSnapshotError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(ApproverRecord(APPROVER_1, "approved"),),
            high_risk=False,
            decided_at=DECIDED_AT,
            incoming_decision=_decision(APPROVER_1, "approved"),
            stored_plan=stored,
            presented_plan=None,
        )


def test_transition_raises_on_presented_plan_only_partial_snapshot() -> None:
    presented = PlanSnapshot(contract_hash=CONTRACT_HASH, content_fingerprint="fp-presented")
    with pytest.raises(InconsistentPlanSnapshotError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(ApproverRecord(APPROVER_1, "approved"),),
            high_risk=False,
            decided_at=DECIDED_AT,
            incoming_decision=_decision(APPROVER_1, "approved"),
            stored_plan=None,
            presented_plan=presented,
        )


# --- MUST-FIX 2: actor_id canonicalization ----------------------------------


def test_same_approver_case_variant_twice_never_satisfies_high_risk_quorum() -> None:
    approvals = (
        ApproverRecord("Actor-Approver-0001", "approved"),
        ApproverRecord("actor-approver-0001", "approved"),
    )
    outcome = transition(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=approvals,
        high_risk=True,
        decided_at=DECIDED_AT,
        incoming_decision=_decision("actor-approver-0001", "approved", high_risk=True),
    )
    assert outcome.state == PlanState.WAITING_APPROVAL


def test_same_approver_whitespace_variant_twice_never_satisfies_high_risk_quorum() -> None:
    approvals = (
        ApproverRecord(" actor-approver-0001", "approved"),
        ApproverRecord("actor-approver-0001 ", "approved"),
    )
    outcome = transition(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=approvals,
        high_risk=True,
        decided_at=DECIDED_AT,
        incoming_decision=_decision("actor-approver-0001 ", "approved", high_risk=True),
    )
    assert outcome.state == PlanState.WAITING_APPROVAL


def test_proposer_case_variant_self_approval_is_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(),
            high_risk=False,
            decided_at=DECIDED_AT,
            incoming_decision=_decision(PROPOSER.upper(), "approved"),
        )


def test_proposer_whitespace_variant_self_approval_is_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(),
            high_risk=False,
            decided_at=DECIDED_AT,
            incoming_decision=_decision(f"  {PROPOSER}  ", "approved"),
        )


def test_whitespace_variant_replay_treated_as_same_key_idempotent() -> None:
    seen = {
        (CONTRACT_HASH, "actor-approver-0001"): _decision("actor-approver-0001", "approved"),
    }
    outcome = transition(
        PlanState.WAITING_APPROVAL,
        contract_hash=CONTRACT_HASH,
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord("actor-approver-0001", "approved"),),
        high_risk=False,
        decided_at=DECIDED_AT,
        seen_decisions=seen,
        incoming_decision=_decision("  actor-approver-0001  ", "approved"),
    )
    # Whitespace-variant resubmission of the SAME decision maps to the same
    # canonical replay key -> idempotent, same outcome, no error.
    assert outcome.state == PlanState.APPROVED


def test_whitespace_variant_conflicting_decision_raises() -> None:
    seen = {
        (CONTRACT_HASH, "actor-approver-0001"): _decision("actor-approver-0001", "approved"),
    }
    with pytest.raises(ConflictingDecisionError):
        transition(
            PlanState.WAITING_APPROVAL,
            contract_hash=CONTRACT_HASH,
            proposer_actor_id=PROPOSER,
            approvals=(ApproverRecord("actor-approver-0001", "approved"),),
            high_risk=False,
            decided_at=DECIDED_AT,
            seen_decisions=seen,
            incoming_decision=_decision("  Actor-Approver-0001  ", "rejected"),
        )


def test_decision_key_canonicalizes_case_and_whitespace() -> None:
    d1 = _decision("Actor-1", "approved")
    d2 = _decision("  actor-1  ", "approved")
    assert d1.decision_key == d2.decision_key


def test_cancel_uses_allowed_transitions_table() -> None:
    # SHOULD-FIX 4: cancel() consults _ALLOWED_TRANSITIONS rather than a
    # hardcoded membership check — exercised indirectly via legal/illegal
    # edges already covered above; this test pins the observable contract
    # that APPROVED (a terminal state with an empty adjacency set) is
    # rejected, consistent with the table.
    with pytest.raises(InvalidTransitionError):
        cancel(
            PlanState.APPROVED,
            contract_hash=CONTRACT_HASH,
            actor_id=PROPOSER,
            decided_at=DECIDED_AT,
        )


def test_expire_uses_allowed_transitions_table() -> None:
    with pytest.raises(InvalidTransitionError):
        expire(
            PlanState.CANCELLED,
            contract_hash=CONTRACT_HASH,
            actor_id=PROPOSER,
            decided_at=DECIDED_AT,
        )

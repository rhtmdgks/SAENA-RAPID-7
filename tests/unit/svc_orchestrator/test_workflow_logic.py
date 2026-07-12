"""Pure workflow_logic core — full §4.3 transition matrix, signal
re-validation (valid->EXECUTING, forged/gate-denied->refused stays
WAITING_APPROVAL), guard_execution reuse, idempotent signal replay."""

from __future__ import annotations

import pytest
from orchestrator_factories import (
    APPROVER_1,
    APPROVER_2,
    CONTRACT_HASH,
    PROPOSER,
    make_decision,
    make_signal,
    make_snapshot,
)
from saena_domain.policy import DecisionRecord, PlanState
from saena_domain.policy.two_person import ApproverRecord
from saena_orchestrator.errors import SignalRefusedError
from saena_orchestrator.workflow_logic import (
    RunState,
    apply_approval_signal,
    require_valid_approval,
)

# --- valid approval -> EXECUTING --------------------------------------------


def test_valid_low_risk_single_approver_signal_transitions_to_executing() -> None:
    signal = make_signal()
    result = apply_approval_signal(PlanState.WAITING_APPROVAL, signal)
    assert result.run_state == RunState.EXECUTING
    assert result.plan_state == PlanState.APPROVED
    assert result.refused_reason is None


def test_require_valid_approval_returns_executing_result_on_success() -> None:
    signal = make_signal()
    result = require_valid_approval(PlanState.WAITING_APPROVAL, signal)
    assert result.run_state == RunState.EXECUTING


def test_require_valid_approval_raises_signal_refused_error_on_forged_signal() -> None:
    forged = make_signal(
        approvals=(ApproverRecord(PROPOSER, "approved"),),
        incoming_decision=make_decision(approver=PROPOSER),  # self-approval == forged
    )
    with pytest.raises(SignalRefusedError):
        require_valid_approval(PlanState.WAITING_APPROVAL, forged)


def test_high_risk_signal_requires_two_distinct_approvers_before_executing() -> None:
    first_only = make_signal(
        approvals=(ApproverRecord(APPROVER_1, "approved"),),
        high_risk=True,
        incoming_decision=make_decision(approver=APPROVER_1, high_risk=True),
    )
    result1 = apply_approval_signal(PlanState.WAITING_APPROVAL, first_only)
    assert result1.run_state == RunState.WAITING_APPROVAL
    assert result1.plan_state == PlanState.WAITING_APPROVAL

    both = make_signal(
        approvals=(
            ApproverRecord(APPROVER_1, "approved"),
            ApproverRecord(APPROVER_2, "approved"),
        ),
        high_risk=True,
        incoming_decision=make_decision(approver=APPROVER_2, high_risk=True),
    )
    result2 = apply_approval_signal(PlanState.WAITING_APPROVAL, both)
    assert result2.run_state == RunState.EXECUTING
    assert result2.plan_state == PlanState.APPROVED


# --- forged / gate-denied signals -> REFUSED, stays WAITING_APPROVAL -------


def test_self_approval_signal_is_refused_not_executing() -> None:
    forged = make_signal(
        approvals=(ApproverRecord(PROPOSER, "approved"),),
        incoming_decision=make_decision(approver=PROPOSER),
    )
    result = apply_approval_signal(PlanState.WAITING_APPROVAL, forged)
    assert result.run_state == RunState.REFUSED
    assert result.plan_state == PlanState.WAITING_APPROVAL
    assert result.refused_reason is not None


def test_contract_hash_mismatch_is_refused() -> None:
    tampered = make_signal(
        incoming_decision=make_decision(contract_hash="sha256:" + "c" * 64),
    )
    result = apply_approval_signal(PlanState.WAITING_APPROVAL, tampered)
    assert result.run_state == RunState.REFUSED
    assert result.plan_state == PlanState.WAITING_APPROVAL


def test_gate_denied_rejected_decision_is_refused_not_executing() -> None:
    rejected = make_signal(
        incoming_decision=make_decision(approver=APPROVER_1, decision="rejected"),
    )
    result = apply_approval_signal(PlanState.WAITING_APPROVAL, rejected)
    assert result.run_state == RunState.REFUSED
    assert result.plan_state == PlanState.REJECTED
    assert result.refused_reason is not None


def test_immutability_violation_is_refused() -> None:
    stored = make_snapshot(content_fingerprint="fp-original")
    presented = make_snapshot(content_fingerprint="fp-tampered")
    signal = make_signal(stored_plan_snapshot=stored, plan_snapshot=presented)
    result = apply_approval_signal(PlanState.WAITING_APPROVAL, signal)
    assert result.run_state == RunState.REFUSED
    assert result.plan_state == PlanState.WAITING_APPROVAL


def test_invalid_current_state_is_refused_not_raised() -> None:
    # A signal arriving when the plan is already APPROVED/terminal must not
    # transition further, and must not raise out of apply_approval_signal —
    # only require_valid_approval raises (SignalRefusedError).
    signal = make_signal()
    result = apply_approval_signal(PlanState.APPROVED, signal)
    assert result.run_state == RunState.REFUSED
    assert result.plan_state == PlanState.APPROVED


# --- full §4.3-adjacent PlanState matrix (via transition() reuse) ----------


@pytest.mark.parametrize(
    "current_state",
    [
        PlanState.APPROVED,
        PlanState.REJECTED,
        PlanState.EXPIRED,
        PlanState.CANCELLED,
    ],
)
def test_signal_against_terminal_plan_state_is_refused(current_state: PlanState) -> None:
    signal = make_signal()
    result = apply_approval_signal(current_state, signal)
    assert result.run_state == RunState.REFUSED
    assert result.plan_state == current_state


# --- idempotent signal replay -----------------------------------------------


def test_identical_signal_replayed_twice_yields_same_single_outcome() -> None:
    signal = make_signal()
    seen: dict[tuple[str, str], DecisionRecord] = {}

    first = apply_approval_signal(PlanState.WAITING_APPROVAL, signal, seen_decisions=seen)
    assert first.run_state == RunState.EXECUTING
    seen[signal.incoming_decision.decision_key] = signal.incoming_decision

    # Replaying the SAME signal a second time (simulating Temporal
    # at-least-once signal delivery) must reach the identical outcome
    # (idempotent replay branch inside saena_domain.policy.transition), not
    # a distinct/duplicate transition or an error.
    second = apply_approval_signal(PlanState.WAITING_APPROVAL, signal, seen_decisions=seen)
    assert second.run_state == RunState.EXECUTING
    assert second.plan_state == first.plan_state


def test_conflicting_replayed_decision_for_same_approver_is_refused() -> None:
    approve_signal = make_signal(
        incoming_decision=make_decision(approver=APPROVER_1, decision="approved"),
    )
    seen: dict[tuple[str, str], DecisionRecord] = {}
    first = apply_approval_signal(PlanState.WAITING_APPROVAL, approve_signal, seen_decisions=seen)
    assert first.run_state == RunState.EXECUTING
    seen[approve_signal.incoming_decision.decision_key] = approve_signal.incoming_decision

    conflicting = make_signal(
        incoming_decision=make_decision(approver=APPROVER_1, decision="rejected"),
    )
    result = apply_approval_signal(PlanState.WAITING_APPROVAL, conflicting, seen_decisions=seen)
    assert result.run_state == RunState.REFUSED


# --- guard_execution reuse: EXECUTING only ever follows a guard_execution- ---
# --- clean APPROVED + "approved" decision -----------------------------------


def test_executing_outcome_always_carries_approved_decision() -> None:
    # apply_approval_signal internally re-runs guard_execution over the
    # resolved outcome (ADR-0003 step 4) — this test asserts that contract
    # indirectly: an ApprovalSignal whose incoming_decision.decision is
    # "approved" and whose plan resolves to APPROVED reaches EXECUTING; the
    # transition()-level guard (self-approval, contract hash, immutability)
    # is exercised by the tests above, so this only needs the direct
    # positive case as a sanity check of the guard_execution call itself.
    signal = make_signal()
    result = apply_approval_signal(PlanState.WAITING_APPROVAL, signal)
    assert result.run_state == RunState.EXECUTING
    assert signal.incoming_decision.decision == "approved"
    assert result.plan_state == PlanState.APPROVED


def test_guard_execution_rejection_after_transition_approved_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # guard_execution() re-running inside apply_approval_signal is a
    # structural defense-in-depth choke point (ADR-0003 step 4) that is not
    # reachable through transition()'s own public contract today (transition
    # only reaches APPROVED via an "approved" incoming_decision, which
    # guard_execution always accepts) — this test exercises that dead-man's
    # switch directly by monkeypatching guard_execution to simulate a future
    # (or defensive) inconsistency between transition()'s APPROVED outcome
    # and guard_execution's own independent check, proving
    # apply_approval_signal refuses rather than executing when they disagree.
    import saena_orchestrator.workflow_logic as workflow_logic_module

    def _always_blocked(*args: object, **kwargs: object) -> None:
        from saena_domain.policy import ExecutionBlockedError

        raise ExecutionBlockedError("simulated guard_execution disagreement")

    monkeypatch.setattr(workflow_logic_module, "guard_execution", _always_blocked)

    signal = make_signal()
    result = apply_approval_signal(PlanState.WAITING_APPROVAL, signal)
    assert result.run_state == RunState.REFUSED
    assert result.plan_state == PlanState.APPROVED
    assert result.refused_reason is not None


def test_contract_hash_constant_matches_sha256_shape() -> None:
    # Sanity guard on the fixture itself (not a domain assertion) — keeps
    # the factories aligned with contract_hash's expected sha256: prefix
    # shape used throughout saena_domain.policy's own tests.
    assert CONTRACT_HASH.startswith("sha256:")

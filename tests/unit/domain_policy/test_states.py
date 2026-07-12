"""PlanState enum sanity + terminal-state set."""

from __future__ import annotations

from saena_domain.policy.states import TERMINAL_STATES, PlanState


def test_plan_state_values_match_k3s_and_contract_vocabulary() -> None:
    assert PlanState.PROPOSED == "proposed"
    assert PlanState.WAITING_APPROVAL == "waiting_approval"
    assert PlanState.APPROVED == "approved"
    assert PlanState.REJECTED == "rejected"
    assert PlanState.EXPIRED == "expired"
    assert PlanState.CANCELLED == "cancelled"


def test_terminal_states_excludes_proposed_and_waiting_approval() -> None:
    assert PlanState.PROPOSED not in TERMINAL_STATES
    assert PlanState.WAITING_APPROVAL not in TERMINAL_STATES
    for state in (
        PlanState.APPROVED,
        PlanState.REJECTED,
        PlanState.EXPIRED,
        PlanState.CANCELLED,
    ):
        assert state in TERMINAL_STATES

"""W2A exit condition 4 (H-7 two-person) at the component-wired level —
high-risk plan through the real `plan-contract-service` HTTP surface, wired
to a REAL `policy-gate-service` app (not `FakeGateClient`)."""

from __future__ import annotations

from approval_factories import (
    APPROVER_1,
    APPROVER_2,
    PROPOSER,
    TENANT_A,
    decision_body,
    high_risk_change_plan,
)
from approval_harness import ApprovalFlowHarness


def _propose(harness: ApprovalFlowHarness, headers: dict[str, str], change_plan: dict) -> str:
    response = harness.plan_contract_client.post("/v1/plans", json=change_plan, headers=headers)
    assert response.status_code == 201
    return response.json()["contract_hash"]


def _configure_gate(harness: ApprovalFlowHarness, contract_hash: str, approver: str) -> None:
    harness.gate_adapter.configure_request_facts(
        tenant_id=TENANT_A,
        contract_hash=contract_hash,
        proposer_actor_id=PROPOSER,
        approver_actor_id=approver,
        hypothesis_risks=("high",),
    )


def test_first_approval_of_high_risk_plan_still_waiting(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str]
) -> None:
    plan = high_risk_change_plan()
    contract_hash = _propose(harness, proposer_headers, plan)
    _configure_gate(harness, contract_hash, APPROVER_1)

    response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, approver_actor_id=APPROVER_1, run_id=plan["run_id"]),
        headers=proposer_headers,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "waiting_approval"


def test_second_distinct_approver_reaches_approved(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str]
) -> None:
    plan = high_risk_change_plan()
    contract_hash = _propose(harness, proposer_headers, plan)
    _configure_gate(harness, contract_hash, APPROVER_1)
    harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, approver_actor_id=APPROVER_1, run_id=plan["run_id"]),
        headers=proposer_headers,
    )

    _configure_gate(harness, contract_hash, APPROVER_2)
    response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, approver_actor_id=APPROVER_2, run_id=plan["run_id"]),
        headers=proposer_headers,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "approved"

    approved_events = [
        e for e in harness.outbox.list_pending() if e["event_type"] == "plan.contract.approved.v1"
    ]
    assert len(approved_events) == 1


def test_same_actor_case_whitespace_variant_second_approval_still_waiting(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str]
) -> None:
    """A case/whitespace variant of the SAME approver dedups to one distinct
    approver (canonical_actor_id) — high-risk quorum (2 DISTINCT) not met."""
    plan = high_risk_change_plan()
    contract_hash = _propose(harness, proposer_headers, plan)
    _configure_gate(harness, contract_hash, APPROVER_1)
    harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, approver_actor_id=APPROVER_1, run_id=plan["run_id"]),
        headers=proposer_headers,
    )

    variant = " Actor-Approver-0001"
    _configure_gate(harness, contract_hash, variant)
    response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, approver_actor_id=variant, run_id=plan["run_id"]),
        headers=proposer_headers,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "waiting_approval"


def test_proposer_self_approval_of_high_risk_plan_is_rejected(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str]
) -> None:
    plan = high_risk_change_plan()
    contract_hash = _propose(harness, proposer_headers, plan)
    _configure_gate(harness, contract_hash, PROPOSER)

    response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, approver_actor_id=PROPOSER, run_id=plan["run_id"]),
        headers=proposer_headers,
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.policy_denied.self_approval"

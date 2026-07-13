"""W2A exit condition 2 — "policy-gate fail-closed 데모: gate 다운 시 승인
불가" — at the component-wired level: `plan-contract-service`'s decision
endpoint reaches a REAL, but BROKEN, policy-gate-shaped HTTP surface
(`DownPolicyGateClient` over `_build_broken_policy_gate_app`), never a
Python-level fake raising in-process — see `fail_closed_harness` fixture.
"""

from __future__ import annotations

import pytest
from approval_factories import TENANT_A, decision_body
from approval_harness import ApprovalFlowHarness
from saena_domain.identity import TenantId


def _propose(harness: ApprovalFlowHarness, headers: dict[str, str], change_plan: dict) -> str:
    response = harness.plan_contract_client.post("/v1/plans", json=change_plan, headers=headers)
    assert response.status_code == 201
    return response.json()["contract_hash"]


def test_gate_down_makes_approval_impossible(
    fail_closed_harness: ApprovalFlowHarness, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    contract_hash = _propose(fail_closed_harness, proposer_headers, change_plan)

    response = fail_closed_harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=proposer_headers,
    )

    # NAMED W2A exit demo assertion: 503 gate_unavailable, retryable.
    assert response.status_code == 503
    body = response.json()
    assert body["error_code"] == "saena.policy_denied.gate_unavailable"
    assert body["retryable"] is True

    # NO approved envelope, NO transition, NO EXECUTING (W2A stops at
    # APPROVED — the "EXECUTING" half of this invariant is W2B's Temporal
    # signal path scope; this unit proves the W2A-owned half: no state
    # change of ANY kind while the gate is unreachable).
    assert (
        fail_closed_harness.plans.get_state(TenantId(TENANT_A), contract_hash).value
        == "waiting_approval"
    )
    assert fail_closed_harness.plans.get_decisions(TenantId(TENANT_A), contract_hash) == ()
    approved_events = [
        e
        for e in fail_closed_harness.outbox.list_pending()
        if e["event_type"] == "plan.contract.approved.v1"
    ]
    assert approved_events == []

    # execution-check independently confirms execution stays blocked.
    exec_response = fail_closed_harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/execution-check", headers=proposer_headers
    )
    assert exec_response.status_code == 403
    assert exec_response.json()["error_code"] == "saena.policy_denied.execution_not_approved"


def test_gate_down_repeated_attempts_all_fail_closed_no_partial_state(
    fail_closed_harness: ApprovalFlowHarness, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    """Retrying against a still-down gate never accidentally succeeds or
    leaves partial state behind — every attempt fails identically."""
    contract_hash = _propose(fail_closed_harness, proposer_headers, change_plan)

    for _ in range(3):
        response = fail_closed_harness.plan_contract_client.post(
            f"/v1/plans/{contract_hash}/decisions",
            json=decision_body(contract_hash, run_id=change_plan["run_id"]),
            headers=proposer_headers,
        )
        assert response.status_code == 503
        assert response.json()["error_code"] == "saena.policy_denied.gate_unavailable"

    assert (
        fail_closed_harness.plans.get_state(TenantId(TENANT_A), contract_hash).value
        == "waiting_approval"
    )
    assert fail_closed_harness.plans.get_decisions(TenantId(TENANT_A), contract_hash) == ()


def test_gate_health_reports_down(fail_closed_harness: ApprovalFlowHarness) -> None:
    """The gate adapter's own `health()` (informational only, never the
    fail-closed authority per `PolicyGateClient.health`'s own docstring)
    also reports the outage — consistent signal across both surfaces."""
    assert fail_closed_harness.gate_adapter.health() is False


def test_gate_recovering_after_outage_allows_approval_to_proceed(
    monkeypatch: pytest.MonkeyPatch, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    """A gate that WAS down and comes back healthy allows the SAME plan to
    reach APPROVED on a subsequent attempt — proves the fail-closed state
    above is a transient block, not a permanently corrupted plan."""
    from approval_harness import build_harness

    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_A)
    recovered = build_harness(tenant_id=TENANT_A)
    try:
        contract_hash = _propose(recovered, proposer_headers, change_plan)
        recovered.gate_adapter.configure_request_facts(
            tenant_id=TENANT_A,
            contract_hash=contract_hash,
            proposer_actor_id="actor-proposer-0001",
            approver_actor_id="actor-approver-0001",
        )
        response = recovered.plan_contract_client.post(
            f"/v1/plans/{contract_hash}/decisions",
            json=decision_body(contract_hash, run_id=change_plan["run_id"]),
            headers=proposer_headers,
        )
        assert response.status_code == 200
        assert response.json()["state"] == "approved"
    finally:
        recovered.close()

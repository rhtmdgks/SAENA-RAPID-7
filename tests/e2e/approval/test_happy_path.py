"""W2A EXIT EVIDENCE — the named end-to-end narrative
(implementation-waves.md:19-22, "승인 E2E(제안→Gate 검증→승인→audit chain),
policy-gate fail-closed 데모(gate 다운 시 승인 불가), deny 우회 회귀... 통과").

`test_full_approval_e2e_propose_gate_approve_audit_chain` is the single
narrative that drives every merged W2A component (forge-console-api,
plan-contract-service, policy-gate-service, audit-ledger-service) through
one coherent story: an operator creates a run via forge-console-api, a
proposer proposes a ChangePlan against plan-contract-service, an approver's
decision is checked by the REAL policy-gate-service over HTTP, the approval
transitions the plan to APPROVED with a `plan.contract.approved.v1` outbox
record, and the full decision trail is relayed into a REAL
audit-ledger-service hash chain that verifies green.

`test_policy_gate_fail_closed_demo` is the NAMED W2A fail-closed demo,
proven again here (in addition to
`tests/integration/approval_flow/test_fail_closed.py`'s component-level
proof) as part of this same end-to-end narrative package, since
implementation-waves.md lists both under the same W2A Exit bullet.
"""

from __future__ import annotations

from approval_factories import APPROVER_1, TENANT_A, decision_body
from approval_harness import ApprovalFlowHarness
from saena_domain.identity import TenantId
from saena_domain.policy import AuditReasonCode


def test_full_approval_e2e_propose_gate_approve_audit_chain(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    # --- Step 0: forge-console-api — operator creates a run record. --------
    run_response = harness.forge_console_client.post(
        "/v1/runs",
        json={"state": "INTAKE", "base_commit": "a" * 40, "human_approval_required": True},
        headers={
            "X-Saena-Actor-Id": "actor-proposer-0001",
            "X-Saena-Session-Id": "session-0001",
            "X-Saena-Actor-Type": "human",
            "X-Saena-Tenant-Id": TENANT_A,
            "X-Saena-Roles": "proposer",
        },
    )
    assert run_response.status_code == 201
    assert run_response.json()["state"] == "INTAKE"

    # --- Step 1: propose — plan-contract-service records the ChangePlan. ---
    propose_response = harness.plan_contract_client.post(
        "/v1/plans", json=change_plan, headers=proposer_headers
    )
    assert propose_response.status_code == 201
    contract_hash = propose_response.json()["contract_hash"]
    assert propose_response.json()["state"] == "waiting_approval"

    proposed_events = [
        e for e in harness.outbox.list_pending() if e["event_type"] == "plan.contract.proposed.v1"
    ]
    assert len(proposed_events) == 1
    assert proposed_events[0]["payload"]["contract_hash"] == contract_hash

    # --- Step 2: Policy Gate 검증 — REAL policy-gate-service HTTP surface. --
    harness.gate_adapter.configure_request_facts(
        tenant_id=TENANT_A,
        contract_hash=contract_hash,
        proposer_actor_id="actor-proposer-0001",
        approver_actor_id=APPROVER_1,
    )

    # --- Step 3: 승인 — approver submits an ApprovalDecision. ---------------
    decision_response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(
            contract_hash, approver_actor_id=APPROVER_1, run_id=change_plan["run_id"]
        ),
        headers=proposer_headers,
    )
    assert decision_response.status_code == 200
    assert decision_response.json()["state"] == "approved"

    # `plan.contract.approved.v1` is in the outbox (transactional-outbox
    # scope for W2A — bus wiring is 2C per implementation-waves.md:23).
    approved_events = [
        e for e in harness.outbox.list_pending() if e["event_type"] == "plan.contract.approved.v1"
    ]
    assert len(approved_events) == 1
    assert approved_events[0]["payload"] == {"contract_hash": contract_hash, "decision": "approved"}
    assert "approver_actor_id" not in approved_events[0]["payload"]  # ADR-0024(e)-2

    # execution-check now allows execution (W2A stops here — W2B owns the
    # Temporal signal / EXECUTING transition per ADR-0003).
    exec_response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/execution-check", headers=proposer_headers
    )
    assert exec_response.status_code == 200
    assert exec_response.json()["execution_allowed"] is True

    # --- Step 4: audit chain — relay the decision trail, verify() green. ---
    records = harness.plan_audit_trail.list_for_plan(TenantId(TENANT_A), contract_hash)
    reason_codes = {r.reason_code for r in records}
    assert AuditReasonCode.SUBMITTED_FOR_APPROVAL in reason_codes
    assert AuditReasonCode.APPROVED_SUFFICIENT_QUORUM in reason_codes

    for index, record in enumerate(records):
        relay_response = harness.audit_relay.relay(
            tenant_id=TENANT_A,
            contract_hash=contract_hash,
            action=f"plan.contract.{record.reason_code.value}.v1",
            recorded_at=record.decided_at,
            trace_id=f"{index:032x}",
            payload={
                "contract_hash": contract_hash,
                "from_state": record.from_state.value,
                "to_state": record.to_state.value,
                "reason_code": record.reason_code.value,
            },
            actor_id=record.actor_id,
        )
        assert relay_response.status_code == 201

    verify_response = harness.audit_relay.verify(tenant_id=TENANT_A)
    assert verify_response.status_code == 200
    assert verify_response.json() == {"ok": True, "first_broken_index": None}

    entries = harness.audit_relay.read_entries(tenant_id=TENANT_A).json()["entries"]
    assert len(entries) == len(records) >= 2


def test_policy_gate_fail_closed_demo(
    fail_closed_harness: ApprovalFlowHarness, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    """NAMED W2A exit demo: gate 다운 시 승인 불가 — plan stays WAITING_APPROVAL,
    HTTP 503 `gate_unavailable`, NO approved envelope, NO EXECUTING (W2A-owned
    half — execution-check independently confirms execution stays blocked)."""
    propose_response = fail_closed_harness.plan_contract_client.post(
        "/v1/plans", json=change_plan, headers=proposer_headers
    )
    assert propose_response.status_code == 201
    contract_hash = propose_response.json()["contract_hash"]

    decision_response = fail_closed_harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=proposer_headers,
    )

    assert decision_response.status_code == 503
    body = decision_response.json()
    assert body["error_code"] == "saena.policy_denied.gate_unavailable"
    assert body["retryable"] is True

    assert (
        fail_closed_harness.plans.get_state(TenantId(TENANT_A), contract_hash).value
        == "waiting_approval"
    )
    approved_events = [
        e
        for e in fail_closed_harness.outbox.list_pending()
        if e["event_type"] == "plan.contract.approved.v1"
    ]
    assert approved_events == []

    exec_response = fail_closed_harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/execution-check", headers=proposer_headers
    )
    assert exec_response.status_code == 403
    assert exec_response.json()["error_code"] == "saena.policy_denied.execution_not_approved"

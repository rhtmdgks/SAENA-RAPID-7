"""W2A exit condition 1's "audit chain contains the decision trail and
verify() is green" — relaying `plan-contract-service`'s in-process
`AuditTrailRecord`s into a REAL `audit-ledger-service` hash-chain (via
`AuditChainRelay`) and proving the chain verifies.
"""

from __future__ import annotations

from approval_factories import APPROVER_1, TENANT_A, decision_body
from approval_harness import ApprovalFlowHarness
from saena_domain.identity import TenantId
from saena_domain.policy import AuditReasonCode


def _propose(harness: ApprovalFlowHarness, headers: dict[str, str], change_plan: dict) -> str:
    response = harness.plan_contract_client.post("/v1/plans", json=change_plan, headers=headers)
    assert response.status_code == 201
    return response.json()["contract_hash"]


def _relay_plan_contract_trail(harness: ApprovalFlowHarness, contract_hash: str) -> None:
    """Copy every `AuditTrailRecord` plan-contract-service produced for this
    plan into the real `audit-ledger-service` chain, in order — the concrete
    relay a future outbox/consumer bridge would perform."""
    records = harness.plan_audit_trail.list_for_plan(TenantId(TENANT_A), contract_hash)
    for index, record in enumerate(records):
        response = harness.audit_relay.relay(
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
        assert response.status_code == 201, response.json()


def test_approval_decision_trail_relayed_into_audit_ledger_verifies(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    contract_hash = _propose(harness, proposer_headers, change_plan)
    harness.gate_adapter.configure_request_facts(
        tenant_id=TENANT_A,
        contract_hash=contract_hash,
        proposer_actor_id="actor-proposer-0001",
        approver_actor_id=APPROVER_1,
    )

    decision_response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=proposer_headers,
    )
    assert decision_response.status_code == 200
    assert decision_response.json()["state"] == "approved"

    # plan-contract-service's OWN audit-trail descriptors exist for both the
    # SUBMITTED_FOR_APPROVAL (at propose) and APPROVED_SUFFICIENT_QUORUM (at
    # decision) transitions.
    records = harness.plan_audit_trail.list_for_plan(TenantId(TENANT_A), contract_hash)
    reason_codes = {r.reason_code for r in records}
    assert AuditReasonCode.SUBMITTED_FOR_APPROVAL in reason_codes
    assert AuditReasonCode.APPROVED_SUFFICIENT_QUORUM in reason_codes

    _relay_plan_contract_trail(harness, contract_hash)

    # The REAL audit-ledger-service chain now contains the decision trail
    # AND verify() is green — the W2A exit condition's exact wording.
    entries_response = harness.audit_relay.read_entries(tenant_id=TENANT_A)
    assert entries_response.status_code == 200
    entries = entries_response.json()["entries"]
    assert len(entries) == len(records)
    actions = [e["action"] for e in entries]
    assert any("submitted_for_approval" in a for a in actions)
    assert any("approved_sufficient_quorum" in a for a in actions)

    verify_response = harness.audit_relay.verify(tenant_id=TENANT_A)
    assert verify_response.status_code == 200
    assert verify_response.json() == {"ok": True, "first_broken_index": None}


def test_audit_chain_is_hash_linked_not_independent_entries(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    """Each relayed entry's `prev_event_hash` chains to the previous entry's
    `event_hash` — proves this is a REAL hash-linked ledger, not a flat
    unlinked log that would trivially "verify"."""
    contract_hash = _propose(harness, proposer_headers, change_plan)
    harness.gate_adapter.configure_request_facts(
        tenant_id=TENANT_A,
        contract_hash=contract_hash,
        proposer_actor_id="actor-proposer-0001",
        approver_actor_id=APPROVER_1,
    )
    harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=proposer_headers,
    )
    _relay_plan_contract_trail(harness, contract_hash)

    entries = harness.audit_relay.read_entries(tenant_id=TENANT_A).json()["entries"]
    assert len(entries) >= 2
    assert entries[0]["prev_event_hash"] is None
    for prior, current in zip(entries, entries[1:], strict=False):
        assert current["prev_event_hash"] == prior["event_hash"]


def test_verify_detects_tamper_on_relayed_chain(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    """`verify()` is not a rubber stamp — direct tamper on the underlying
    `InMemoryAuditLedger` (white-box, mirrors
    `tests/unit/svc_audit_ledger/test_verify.py`'s own technique) is
    detected through the SAME relayed-from-plan-contract chain."""
    contract_hash = _propose(harness, proposer_headers, change_plan)
    harness.gate_adapter.configure_request_facts(
        tenant_id=TENANT_A,
        contract_hash=contract_hash,
        proposer_actor_id="actor-proposer-0001",
        approver_actor_id=APPROVER_1,
    )
    harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=proposer_headers,
    )
    _relay_plan_contract_trail(harness, contract_hash)

    ok_before, _ = harness.ledger.verify(tenant_id=TenantId(TENANT_A))
    assert ok_before is True

    stored = harness.ledger._tenant_chains[TENANT_A]  # noqa: SLF001
    tampered = stored[0].model_copy(update={"payload": {"tampered": True}})
    stored[0] = tampered

    verify_response = harness.audit_relay.verify(tenant_id=TENANT_A)
    assert verify_response.json() == {"ok": False, "first_broken_index": 0}

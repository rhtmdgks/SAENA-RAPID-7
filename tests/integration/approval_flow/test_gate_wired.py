"""Component-wired proof: plan-contract-service's decision endpoint reaches
a REAL `policy-gate-service` HTTP surface (not `FakeGateClient`) via
`PlanContractHttpGateAdapter` — W2A exit condition 1 (gate verification) and
condition 6 (ADR-0003 order: gate-denied => no transition) at the
integration level, mirroring the unit-level proof in
`tests/unit/svc_plan_contract/test_decisions.py` but through the actual
wired HTTP boundary between the two services.
"""

from __future__ import annotations

from approval_factories import TENANT_A, decision_body, load_change_plan_fixture
from approval_harness import ApprovalFlowHarness
from saena_domain.identity import TenantId


def _propose(harness: ApprovalFlowHarness, headers: dict[str, str], change_plan: dict) -> str:
    response = harness.plan_contract_client.post("/v1/plans", json=change_plan, headers=headers)
    assert response.status_code == 201
    return response.json()["contract_hash"]


def test_decision_reaches_approved_via_real_policy_gate_http_surface(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str], change_plan: dict
) -> None:
    contract_hash = _propose(harness, proposer_headers, change_plan)
    harness.gate_adapter.configure_request_facts(
        tenant_id=TENANT_A,
        contract_hash=contract_hash,
        proposer_actor_id="actor-proposer-0001",
        approver_actor_id="actor-approver-0001",
    )

    response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=proposer_headers,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "approved"

    # Proof this went through the REAL policy-gate app, not a fake/stub: the
    # gate's OWN `DecisionRecordPort` now durably holds a record for this
    # exact plan-check, keyed the same way `saena_policy_gate.service`
    # constructs `decision_key` (contract_hash, canonical_actor_id(approver)).
    from saena_domain.policy.identity import canonical_actor_id

    stored = harness.policy_gate_decision_store.get(
        TenantId(TENANT_A), (contract_hash, canonical_actor_id("actor-approver-0001"))
    )
    assert stored.decision == "approved"


def test_real_gate_denial_blocks_transition_no_approval_possible(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str]
) -> None:
    """ADR-0003 order at the integration level: a REAL H-3 scope-escape
    violation evaluated by policy-gate-service's own
    `evaluate_h3_evidence_policy` produces `decision: "deny"` over the wire;
    plan-contract-service's `submit_decision` must stop BEFORE
    `saena_domain.policy.transition()` is ever called — no state change, no
    decision recorded, no approved envelope.

    The PROPOSED plan itself is schema/H-3-valid (`propose_plan` runs its
    own H-3 check too, on the plan's OWN `approved_scope` — a scope-escaping
    plan would never even reach WAITING_APPROVAL); the escaping scope is
    injected only into the GATE request `configure_request_facts` sends,
    exercising the gate's independent H-3 re-evaluation at decision time.
    """
    plan = load_change_plan_fixture("single-patch-unit.json", tenant_id=TENANT_A)
    contract_hash = _propose(harness, proposer_headers, plan)
    harness.gate_adapter.configure_request_facts(
        tenant_id=TENANT_A,
        contract_hash=contract_hash,
        proposer_actor_id="actor-proposer-0001",
        approver_actor_id="actor-approver-0001",
        approved_scope=("../etc/passwd",),
    )

    response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=plan["run_id"]),
        headers=proposer_headers,
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.policy_denied.gate_denied"

    # No transition: plan is still WAITING_APPROVAL, no decision recorded,
    # no plan.contract.approved.v1 in the outbox.
    assert harness.plans.get_state(TenantId(TENANT_A), contract_hash).value == "waiting_approval"
    assert harness.plans.get_decisions(TenantId(TENANT_A), contract_hash) == ()
    approved_events = [
        e for e in harness.outbox.list_pending() if e["event_type"] == "plan.contract.approved.v1"
    ]
    assert approved_events == []


def test_real_gate_denial_reason_is_surfaced_from_h3_evaluator(
    harness: ApprovalFlowHarness, proposer_headers: dict[str, str]
) -> None:
    """The deny reason plan-contract-service records/raises traces back to
    policy-gate-service's OWN H-3 evaluator output (not a canned/stubbed
    reason) — proves the two services' real decision payload round-trips."""
    plan = load_change_plan_fixture("single-patch-unit.json", tenant_id=TENANT_A)
    contract_hash = _propose(harness, proposer_headers, plan)
    harness.gate_adapter.configure_request_facts(
        tenant_id=TENANT_A,
        contract_hash=contract_hash,
        proposer_actor_id="actor-proposer-0001",
        approver_actor_id="actor-approver-0001",
        approved_scope=("../etc/passwd",),
    )

    # Confirm directly against the real gate app what reason it computed.
    gate_response = harness.policy_gate_client.post(
        "/v1/gate/plan-check",
        json={
            "contract_hash": contract_hash,
            "proposer_actor_id": "actor-proposer-0001",
            "approver_actor_id": "actor-approver-0001",
            "evidence_ledger_hash": "sha256:" + "a" * 64,
            "approved_scope": ["../etc/passwd"],
            "scope_max_globs": 5,
            "diff_max_files": 10,
            "diff_max_lines": 500,
            "hypothesis_risks": ["low"],
            "diff_stats": None,
        },
        headers={"X-Saena-Tenant-Id": TENANT_A},
    )
    assert gate_response.status_code == 200
    assert gate_response.json()["decision"] == "deny"
    assert "scope glob escapes declared roots" in gate_response.json()["reasons"][0]

    response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=plan["run_id"]),
        headers=proposer_headers,
    )
    assert response.status_code == 403

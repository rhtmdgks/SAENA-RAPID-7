"""POST /v1/plans/{contract_hash}/decisions — ADR-0003 order, H-7, idempotency."""

from __future__ import annotations

import pytest
import saena_plan_contract.app as plan_contract_app_module
from fastapi.testclient import TestClient
from plan_contract_factories import (
    APPROVER_1,
    APPROVER_2,
    TENANT_ID,
    decision_body,
    high_risk_change_plan,
)
from saena_domain.persistence import InMemoryOutbox, InMemoryPlanRepository
from saena_domain.policy.lease import PatchUnitLease
from saena_plan_contract import create_app
from saena_plan_contract.audit_trail import AuditTrailStore
from saena_plan_contract.gate_client import FakeGateClient


def _propose(client, headers, change_plan) -> str:
    response = client.post("/v1/plans", json=change_plan, headers=headers)
    assert response.status_code == 201
    return response.json()["contract_hash"]


def test_decision_with_gate_allow_reaches_approved(client, headers, change_plan, outbox) -> None:
    contract_hash = _propose(client, headers, change_plan)
    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "approved"

    approved_events = [
        e for e in outbox.list_pending() if e["event_type"] == "plan.contract.approved.v1"
    ]
    assert len(approved_events) == 1
    payload = approved_events[0]["payload"]
    assert payload == {"contract_hash": contract_hash, "decision": "approved"}
    assert "approver_actor_id" not in payload


def test_approved_lease_scope_matches_plan_approved_scope(
    client, headers, change_plan, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard (critic MUST-FIX, re-verify of w2-21): `app.py`'s
    APPROVED branch previously hardcoded `issue_lease(..., scope=(), ...)`
    — every lease was issued with an EMPTY scope regardless of what the plan
    actually declared, even though `plan_facts["approved_scope"]` (the same
    value the gate request now uses, `w2-21`) was already in scope at that
    call site. `issue_lease`'s return value is not persisted or exposed over
    HTTP (`app.py`'s own module docstring / `issue_lease`'s own docstring —
    "pure construction only"), so this monkeypatches `issue_lease` in
    `app.py`'s own module namespace to capture what it was actually called
    with — the only way to observe this from outside `app.py`."""
    calls: list[dict[str, object]] = []

    def _capturing_issue_lease(
        *, patch_unit_id: str, scope: tuple[str, ...], expiry: str
    ) -> PatchUnitLease:
        calls.append({"patch_unit_id": patch_unit_id, "scope": scope, "expiry": expiry})
        return PatchUnitLease(patch_unit_id=patch_unit_id, scope=scope, expiry=expiry)

    monkeypatch.setattr(plan_contract_app_module, "issue_lease", _capturing_issue_lease)

    contract_hash = _propose(client, headers, change_plan)
    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "approved"

    assert len(calls) == 1
    assert calls[0]["patch_unit_id"] == change_plan["patch_units"][0]["id"]
    assert calls[0]["scope"] == tuple(change_plan["approved_scope"])
    assert calls[0]["scope"] != ()


def test_gate_denied_before_any_transition(client, headers, change_plan, gate, plans) -> None:
    from saena_domain.identity import TenantId

    contract_hash = _propose(client, headers, change_plan)
    gate.mode = "deny"

    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.policy_denied.gate_denied"
    # NO transition: plan is still WAITING_APPROVAL, no decision recorded.
    assert plans.get_state(TenantId("acme-corp"), contract_hash).value == "waiting_approval"
    assert plans.get_decisions(TenantId("acme-corp"), contract_hash) == ()


def test_gate_unavailable_before_any_transition_fail_closed(
    client, headers, change_plan, gate, plans, outbox
) -> None:
    from saena_domain.identity import TenantId

    contract_hash = _propose(client, headers, change_plan)
    gate.mode = "down"

    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=headers,
    )
    assert response.status_code == 503
    assert response.json()["error_code"] == "saena.policy_denied.gate_unavailable"
    assert response.json()["retryable"] is True
    # NO transition, NO approved envelope — approval is IMPOSSIBLE while the
    # gate is down (ADR-0003/W2A exit-demo fail-closed path).
    assert plans.get_state(TenantId("acme-corp"), contract_hash).value == "waiting_approval"
    approved_events = [
        e for e in outbox.list_pending() if e["event_type"] == "plan.contract.approved.v1"
    ]
    assert approved_events == []


def test_two_person_first_approval_still_waiting(client, headers) -> None:
    plan = high_risk_change_plan()
    contract_hash = _propose(client, headers, plan)
    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, approver_actor_id=APPROVER_1, run_id=plan["run_id"]),
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "waiting_approval"


def test_two_person_second_distinct_approver_reaches_approved(client, headers) -> None:
    plan = high_risk_change_plan()
    contract_hash = _propose(client, headers, plan)
    client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, approver_actor_id=APPROVER_1, run_id=plan["run_id"]),
        headers=headers,
    )
    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, approver_actor_id=APPROVER_2, run_id=plan["run_id"]),
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "approved"


def test_two_person_same_actor_case_variant_second_not_approved(client, headers) -> None:
    plan = high_risk_change_plan()
    contract_hash = _propose(client, headers, plan)
    client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, approver_actor_id=APPROVER_1, run_id=plan["run_id"]),
        headers=headers,
    )
    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(
            contract_hash, approver_actor_id=" Actor-Approver-0001", run_id=plan["run_id"]
        ),
        headers=headers,
    )
    assert response.status_code == 200
    # Case/whitespace variant of the SAME approver dedups to one distinct
    # approver — high-risk quorum (2 distinct) is NOT satisfied.
    assert response.json()["state"] == "waiting_approval"


def test_self_approval_is_rejected(client, headers, change_plan) -> None:
    contract_hash = _propose(client, headers, change_plan)
    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(
            contract_hash, approver_actor_id="actor-proposer-0001", run_id=change_plan["run_id"]
        ),
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.policy_denied.self_approval"


def test_idempotent_replay_no_duplicate_envelope(client, headers, change_plan, outbox) -> None:
    contract_hash = _propose(client, headers, change_plan)
    body = decision_body(contract_hash, run_id=change_plan["run_id"])
    first = client.post(f"/v1/plans/{contract_hash}/decisions", json=body, headers=headers)
    assert first.status_code == 200
    event_ids_before = {e["event_id"] for e in outbox.list_pending()}

    second = client.post(f"/v1/plans/{contract_hash}/decisions", json=body, headers=headers)
    assert second.status_code == 200
    assert second.json() == first.json()
    event_ids_after = {e["event_id"] for e in outbox.list_pending()}
    assert event_ids_after == event_ids_before


def test_idempotent_replay_case_whitespace_variant_approver(
    client, headers, change_plan, outbox
) -> None:
    contract_hash = _propose(client, headers, change_plan)
    client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(
            contract_hash, approver_actor_id=APPROVER_1, run_id=change_plan["run_id"]
        ),
        headers=headers,
    )
    event_ids_before = {e["event_id"] for e in outbox.list_pending()}

    replay = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(
            contract_hash, approver_actor_id=" Actor-Approver-0001 ", run_id=change_plan["run_id"]
        ),
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json()["state"] == "approved"
    event_ids_after = {e["event_id"] for e in outbox.list_pending()}
    assert event_ids_after == event_ids_before


def test_conflicting_decision_after_settled_is_409(client, headers, change_plan) -> None:
    contract_hash = _propose(client, headers, change_plan)
    client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=headers,
    )
    conflicting = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, decision="rejected", run_id=change_plan["run_id"]),
        headers=headers,
    )
    assert conflicting.status_code == 409


def test_conflicting_decision_before_settlement_is_409(client, headers) -> None:
    """Same approver submits 'approved' then 'rejected' for a still-pending
    (WAITING_APPROVAL, not yet settled) high-risk plan — conflict is detected
    even though the plan itself hasn't reached a terminal state yet."""
    plan = high_risk_change_plan()
    contract_hash = _propose(client, headers, plan)
    client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, approver_actor_id=APPROVER_1, run_id=plan["run_id"]),
        headers=headers,
    )
    conflicting = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(
            contract_hash, approver_actor_id=APPROVER_1, decision="rejected", run_id=plan["run_id"]
        ),
        headers=headers,
    )
    assert conflicting.status_code == 409


def test_decision_invalid_schema_body_is_400(client, headers, change_plan) -> None:
    contract_hash = _propose(client, headers, change_plan)
    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json={"not": "an approval decision"},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "saena.validation.schema_mismatch"


def test_decision_contract_hash_mismatch_is_400(client, headers, change_plan) -> None:
    contract_hash = _propose(client, headers, change_plan)
    other_hash = "sha256:" + "b" * 64
    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(other_hash, run_id=change_plan["run_id"]),
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "saena.validation.contract_hash_mismatch"


def test_decision_for_unknown_plan_is_404(client, headers) -> None:
    unknown_hash = "sha256:" + "c" * 64
    response = client.post(
        f"/v1/plans/{unknown_hash}/decisions",
        json=decision_body(unknown_hash),
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "saena.not_found.resource_missing"


def test_rejected_decision_reaches_rejected_and_no_approved_envelope(
    client, headers, change_plan, outbox
) -> None:
    contract_hash = _propose(client, headers, change_plan)
    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, decision="rejected", run_id=change_plan["run_id"]),
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "rejected"

    rejected_events = [
        e for e in outbox.list_pending() if e["event_type"] == "plan.contract.approved.v1"
    ]
    assert len(rejected_events) == 1
    assert rejected_events[0]["payload"]["decision"] == "rejected"


def test_toctou_race_on_record_decision_is_409(headers, change_plan) -> None:
    """`transition()`'s own conflict check reads `seen_decisions` at the
    START of `submit_decision` — between that read and the
    `plans.record_decision` write, a concurrent request could have already
    recorded a CONFLICTING decision for the same `decision_key`. This test
    forces exactly that race deterministically (a single-threaded repo
    subclass that injects a conflicting write right before the real one)
    to prove the repo-layer `DecisionConflictError` catch in
    `submit_decision` is live defense-in-depth, not dead code."""
    from saena_domain.persistence.errors import DecisionConflictError
    from saena_domain.policy import DecisionRecord

    class RacyPlanRepository(InMemoryPlanRepository):
        def record_decision(self, tenant_id, decision: DecisionRecord) -> DecisionRecord:
            racing = DecisionRecord(
                contract_hash=decision.contract_hash,
                approver_actor_id=decision.approver_actor_id,
                decision="rejected" if decision.decision == "approved" else "approved",
                proposer_actor_id=decision.proposer_actor_id,
                high_risk=decision.high_risk,
                decided_at=decision.decided_at,
            )
            super().record_decision(tenant_id, racing)
            raise DecisionConflictError(
                "simulated concurrent conflicting write",
                context={"decision_key": list(decision.decision_key)},
            )

    plans = RacyPlanRepository()
    outbox = InMemoryOutbox()
    gate = FakeGateClient()
    app = create_app(
        plans=plans,
        outbox=outbox,
        gate=gate,
        audit_trail=AuditTrailStore(),
        tenant_env_value=TENANT_ID,
    )
    client = TestClient(app)

    contract_hash = _propose(client, headers, change_plan)
    response = client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "saena.conflict.decision_conflict"

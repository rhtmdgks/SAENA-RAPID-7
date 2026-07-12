"""cancel/expire/execution-check/GET — audit records + execution-block invariant."""

from __future__ import annotations

from plan_contract_factories import decision_body


def _propose(client, headers, change_plan) -> str:
    response = client.post("/v1/plans", json=change_plan, headers=headers)
    assert response.status_code == 201
    return response.json()["contract_hash"]


def test_execution_check_before_approval_is_403(client, headers, change_plan) -> None:
    contract_hash = _propose(client, headers, change_plan)
    response = client.post(f"/v1/plans/{contract_hash}/execution-check", headers=headers)
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.policy_denied.execution_not_approved"


def test_execution_check_after_approval_is_200(client, headers, change_plan) -> None:
    contract_hash = _propose(client, headers, change_plan)
    client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=headers,
    )
    response = client.post(f"/v1/plans/{contract_hash}/execution-check", headers=headers)
    assert response.status_code == 200
    assert response.json()["execution_allowed"] is True


def test_cancel_from_waiting_approval_produces_audit_record(
    client, headers, change_plan, audit_trail
) -> None:
    from saena_domain.identity import TenantId
    from saena_domain.policy import AuditReasonCode

    contract_hash = _propose(client, headers, change_plan)
    response = client.post(f"/v1/plans/{contract_hash}/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json()["state"] == "cancelled"

    records = audit_trail.list_for_plan(TenantId("acme-corp"), contract_hash)
    assert any(r.reason_code == AuditReasonCode.CANCELLED_BY_PROPOSER for r in records)


def test_cancel_by_operator_produces_distinct_audit_reason(
    client, headers, change_plan, audit_trail
) -> None:
    from saena_domain.identity import TenantId
    from saena_domain.policy import AuditReasonCode

    contract_hash = _propose(client, headers, change_plan)
    response = client.post(
        f"/v1/plans/{contract_hash}/cancel",
        headers={**headers, "X-Saena-Operator": "true"},
    )
    assert response.status_code == 200
    records = audit_trail.list_for_plan(TenantId("acme-corp"), contract_hash)
    assert any(r.reason_code == AuditReasonCode.CANCELLED_BY_OPERATOR for r in records)


def test_expire_from_waiting_approval_produces_audit_record(
    client, headers, change_plan, audit_trail
) -> None:
    from saena_domain.identity import TenantId
    from saena_domain.policy import AuditReasonCode

    contract_hash = _propose(client, headers, change_plan)
    response = client.post(f"/v1/plans/{contract_hash}/expire", headers=headers)
    assert response.status_code == 200
    assert response.json()["state"] == "expired"

    records = audit_trail.list_for_plan(TenantId("acme-corp"), contract_hash)
    assert any(r.reason_code == AuditReasonCode.EXPIRED_LEASE_WINDOW for r in records)


def test_cancel_after_approval_is_409(client, headers, change_plan) -> None:
    contract_hash = _propose(client, headers, change_plan)
    client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=headers,
    )
    response = client.post(f"/v1/plans/{contract_hash}/cancel", headers=headers)
    assert response.status_code == 409


def test_expire_after_approval_is_409(client, headers, change_plan) -> None:
    contract_hash = _propose(client, headers, change_plan)
    client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=headers,
    )
    response = client.post(f"/v1/plans/{contract_hash}/expire", headers=headers)
    assert response.status_code == 409


def test_cancel_unknown_plan_is_404(client, headers) -> None:
    response = client.post(
        f"/v1/plans/sha256:{'d' * 64}/cancel",
        headers=headers,
    )
    assert response.status_code == 404


def test_get_plan_state_returns_state_and_decisions_actor_id_only(
    client, headers, change_plan
) -> None:
    contract_hash = _propose(client, headers, change_plan)
    client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(contract_hash, run_id=change_plan["run_id"]),
        headers=headers,
    )
    response = client.get(f"/v1/plans/{contract_hash}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "approved"
    assert len(body["decisions"]) == 1
    decision = body["decisions"][0]
    assert set(decision.keys()) == {"approver_actor_id", "decision", "decided_at"}


def test_expire_unknown_plan_is_404(client, headers) -> None:
    response = client.post(f"/v1/plans/sha256:{'f' * 64}/expire", headers=headers)
    assert response.status_code == 404
    assert response.json()["error_code"] == "saena.not_found.resource_missing"


def test_execution_check_unknown_plan_is_404(client, headers) -> None:
    response = client.post(f"/v1/plans/sha256:{'0' * 64}/execution-check", headers=headers)
    assert response.status_code == 404
    assert response.json()["error_code"] == "saena.not_found.resource_missing"


def test_get_plan_state_unknown_plan_is_404(client, headers) -> None:
    response = client.get(f"/v1/plans/sha256:{'e' * 64}", headers=headers)
    assert response.status_code == 404
    assert response.json()["error_code"] == "saena.not_found.resource_missing"

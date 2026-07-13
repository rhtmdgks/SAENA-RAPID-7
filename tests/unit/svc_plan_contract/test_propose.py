"""POST /v1/plans — propose happy path + validation/immutability edges."""

from __future__ import annotations

from plan_contract_factories import mutate_scope


def test_propose_happy_path_returns_waiting_approval(client, headers, change_plan) -> None:
    response = client.post("/v1/plans", json=change_plan, headers=headers)
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "waiting_approval"
    assert body["contract_hash"].startswith("sha256:")


def test_propose_records_proposed_envelope_in_outbox(client, headers, change_plan, outbox) -> None:
    response = client.post("/v1/plans", json=change_plan, headers=headers)
    contract_hash = response.json()["contract_hash"]

    pending = outbox.list_pending()
    assert len(pending) == 1
    envelope = pending[0]
    assert envelope["event_type"] == "plan.contract.proposed.v1"
    assert envelope["context_type"] == "tenant"
    assert envelope["payload"]["contract_hash"] == contract_hash
    assert envelope["payload"]["base_commit"] == change_plan["repo_commit"]
    assert envelope["idempotency_key"] == contract_hash


def test_propose_missing_actor_header_is_validation_error(client, change_plan) -> None:
    response = client.post(
        "/v1/plans", json=change_plan, headers={"X-Saena-Tenant-Id": "acme-corp"}
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "saena.validation.schema_mismatch"


def test_propose_invalid_schema_body_is_rejected(client, headers) -> None:
    response = client.post("/v1/plans", json={"not": "a change plan"}, headers=headers)
    assert response.status_code == 400
    assert response.json()["error_code"] == "saena.validation.schema_mismatch"


def test_propose_tenant_mismatch_between_header_and_env_is_403(app_factory, change_plan) -> None:
    from fastapi.testclient import TestClient

    app = app_factory()
    client = TestClient(app)
    response = client.post(
        "/v1/plans",
        json=change_plan,
        headers={"X-Saena-Tenant-Id": "someone-else", "X-Saena-Actor-Id": "actor-proposer-0001"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.auth.tenant_mismatch"


def test_propose_change_plan_tenant_id_mismatch_is_validation_error(
    client, headers, change_plan
) -> None:
    change_plan["tenant_id"] = "different-tenant-value"
    response = client.post("/v1/plans", json=change_plan, headers=headers)
    assert response.status_code == 400
    assert response.json()["error_code"] == "saena.validation.schema_mismatch"


def test_propose_identical_content_is_idempotent(client, headers, change_plan) -> None:
    first = client.post("/v1/plans", json=change_plan, headers=headers)
    second = client.post("/v1/plans", json=change_plan, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["contract_hash"] == second.json()["contract_hash"]


def test_propose_different_content_yields_different_contract_hash(
    client, headers, change_plan
) -> None:
    first = client.post("/v1/plans", json=change_plan, headers=headers)
    mutated = mutate_scope(change_plan, "apps/web/extra/*")
    second = client.post("/v1/plans", json=mutated, headers=headers)
    assert first.json()["contract_hash"] != second.json()["contract_hash"]


def test_propose_h3_scope_glob_escape_is_validation_error(client, headers, change_plan) -> None:
    change_plan["approved_scope"] = [*change_plan["approved_scope"], "../../etc/passwd"]
    response = client.post("/v1/plans", json=change_plan, headers=headers)
    assert response.status_code == 400
    assert response.json()["error_code"] == "saena.validation.schema_mismatch"
    assert "H-3" in response.json()["detail"]


def test_mutated_plan_content_reusing_same_contract_hash_is_contract_hash_violation(
    client, headers, change_plan, plans
) -> None:
    """`contract_hash` is content-addressed (see `contract_hash.py`), so a
    real HTTP client cannot naturally construct "same hash, different
    content" — this test forces the collision directly at the
    `PlanRepository` layer (the same technique
    `saena_domain.policy`'s own `guard_immutability` unit tests use) to prove
    `propose_plan`'s explicit content-fingerprint comparison actually fires a
    409 `PlanContractHashViolationError`, not merely a silent overwrite."""
    from saena_domain.policy import PlanSnapshot

    first = client.post("/v1/plans", json=change_plan, headers=headers)
    contract_hash = first.json()["contract_hash"]

    # Directly corrupt the stored snapshot's content_fingerprint to simulate
    # "same contract_hash key, different content" — put_plan is a dumb
    # upsert (its own docstring: "the port only persists whatever
    # PlanSnapshot it is given"), so this bypasses compute_contract_hash's
    # collision-resistance entirely, on purpose, for this one test.
    from saena_domain.identity import TenantId

    plans.put_plan(
        TenantId("acme-corp"),
        PlanSnapshot(contract_hash=contract_hash, content_fingerprint="tampered-fingerprint"),
    )

    second = client.post("/v1/plans", json=change_plan, headers=headers)
    assert second.status_code == 409
    assert second.json()["error_code"] == "saena.conflict.contract_hash_violation"

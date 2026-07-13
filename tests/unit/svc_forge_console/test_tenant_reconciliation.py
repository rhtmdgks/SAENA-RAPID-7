"""`X-Saena-Tenant-Id` vs pod env `SAENA_TENANT_ID` mismatch -> 403
(ADR-0014 synchronous HTTP propagation path)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from svc_forge_console.conftest import DEFAULT_TENANT, OTHER_TENANT, actor_headers, run_create_body


def test_mismatched_tenant_header_returns_403(client: TestClient) -> None:
    response = client.post(
        "/v1/runs",
        json=run_create_body(),
        headers=actor_headers(tenant_id=OTHER_TENANT, roles="proposer"),
    )
    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "saena.policy_denied.tenant_mismatch"
    assert body["type"] == "https://schemas.the-saena.ai/errors/policy_denied/tenant_mismatch"


def test_mismatch_response_is_problem_json(client: TestClient) -> None:
    response = client.post(
        "/v1/runs",
        json=run_create_body(),
        headers=actor_headers(tenant_id=OTHER_TENANT, roles="proposer"),
    )
    assert response.headers["content-type"] == "application/problem+json"


def test_missing_pod_env_treated_as_mismatch(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.delenv("SAENA_TENANT_ID", raising=False)
    response = client.post(
        "/v1/runs",
        json=run_create_body(),
        headers=actor_headers(tenant_id=DEFAULT_TENANT, roles="proposer"),
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.policy_denied.tenant_mismatch"


def test_no_tenant_header_at_all_skips_reconciliation(client: TestClient) -> None:
    # No X-Saena-Tenant-Id at all -> reconciliation middleware skips this
    # request entirely (module docstring); whoami has no tenant requirement
    # so this is a clean way to prove the skip without a downstream route
    # rejecting the request for an unrelated (missing-tenant_id) reason.
    headers = actor_headers(tenant_id=None, actor_type="system")
    response = client.get("/v1/actor/whoami", headers=headers)
    assert response.status_code == 200


def test_matching_tenant_header_and_env_succeeds(client: TestClient) -> None:
    response = client.post(
        "/v1/runs",
        json=run_create_body(),
        headers=actor_headers(tenant_id=DEFAULT_TENANT, roles="proposer"),
    )
    assert response.status_code == 201

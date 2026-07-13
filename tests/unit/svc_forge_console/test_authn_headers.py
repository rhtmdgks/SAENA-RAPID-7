"""`saena_forge_console.authn` header-parsing edge cases not already covered
by route-level tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from svc_forge_console.conftest import actor_headers


def test_unknown_role_token_is_rejected(client: TestClient) -> None:
    headers = actor_headers(roles="not-a-real-role")
    response = client.get("/v1/actor/whoami", headers=headers)
    assert response.status_code == 422
    assert response.json()["error_code"] == "saena.validation.unknown_role"


def test_multiple_roles_comma_separated(client: TestClient) -> None:
    headers = actor_headers(roles="proposer, auditor")
    response = client.get("/v1/lineage/audit:sha256:" + "a" * 64, headers=headers)
    # auditor is among the roles -> view_lineage granted (404, no seeded
    # record -- but NOT 403, proving both roles parsed and the auditor one
    # was honored).
    assert response.status_code == 404


def test_invalid_actor_type_header_is_rejected(client: TestClient) -> None:
    headers = actor_headers(roles=None)
    headers["X-Saena-Actor-Type"] = "robot"
    response = client.get("/v1/actor/whoami", headers=headers)
    assert response.status_code == 422
    assert response.json()["error_code"] == "saena.validation.invalid_actor_type"


def test_empty_roles_header_resolves_to_no_roles(client: TestClient) -> None:
    headers = actor_headers(roles=None)
    headers["X-Saena-Roles"] = "   "
    response = client.post(
        "/v1/runs",
        json={"state": "INTAKE", "base_commit": "a" * 40, "human_approval_required": True},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.policy_denied.permission_denied"


def test_default_actor_type_is_human(client: TestClient) -> None:
    headers = actor_headers(roles=None, tenant_id="acme-corp")
    del headers["X-Saena-Actor-Type"]
    response = client.get("/v1/actor/whoami", headers=headers)
    assert response.status_code == 200
    assert response.json()["actor_type"] == "human"

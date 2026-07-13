"""`GET /v1/actor/whoami` — PII-safe echo of the caller's `ActorContext`."""

from __future__ import annotations

from fastapi.testclient import TestClient

from svc_forge_console.conftest import DEFAULT_TENANT, actor_headers


def test_whoami_echoes_actor_id_and_session_id(client: TestClient) -> None:
    response = client.get(
        "/v1/actor/whoami",
        headers=actor_headers(actor_id="actor-42", session_id="session-42", roles=None),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["actor_id"] == "actor-42"
    assert body["session_id"] == "session-42"
    assert body["actor_type"] == "human"
    assert body["tenant_id"] == DEFAULT_TENANT


def test_whoami_pii_safe_response_shape(client: TestClient) -> None:
    """The response body carries only actor_id/actor_type/session_id/tenant_id
    -- no display_name/email/role, matching the generated ActorContext
    schema's structural PII-omission (contract-catalog.md:20)."""
    response = client.get("/v1/actor/whoami", headers=actor_headers(roles=None))
    assert set(response.json().keys()) == {"actor_id", "actor_type", "session_id", "tenant_id"}


def test_whoami_system_actor_without_tenant(client: TestClient) -> None:
    response = client.get(
        "/v1/actor/whoami",
        headers=actor_headers(actor_type="system", tenant_id=None, roles=None),
    )
    assert response.status_code == 200
    assert response.json()["tenant_id"] is None


def test_whoami_missing_actor_id_header_is_auth_error(client: TestClient) -> None:
    headers = actor_headers(roles=None)
    del headers["X-Saena-Actor-Id"]
    response = client.get("/v1/actor/whoami", headers=headers)
    assert response.status_code == 401
    assert response.json()["error_code"] == "saena.auth.actor_id_required"


def test_whoami_missing_session_id_header_is_auth_error(client: TestClient) -> None:
    headers = actor_headers(roles=None)
    del headers["X-Saena-Session-Id"]
    response = client.get("/v1/actor/whoami", headers=headers)
    assert response.status_code == 401
    assert response.json()["error_code"] == "saena.auth.session_id_required"

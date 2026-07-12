"""HTTP-level tests for `saena_tenant_control` (ADR-0014/ADR-0015).

Uses `fastapi.testclient.TestClient` (httpx under the hood, task spec) with
`create_app(InMemoryTenantRepository(), InMemoryOutbox())` — no real network
I/O, no SQL. Every test sets `X-Saena-Tenant-Id`/`SAENA_TENANT_ID` to the
same value (`TENANT_A`) unless the test is specifically about a mismatch.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from saena_domain.identity import TENANT_ENV_VAR_NAME
from saena_domain.persistence import InMemoryOutbox, InMemoryTenantRepository
from saena_tenant_control import create_app
from tenant_control_factories import HEADER_NAME, TENANT_A, TENANT_B, create_payload


def _headers(tenant_id: str = TENANT_A) -> dict[str, str]:
    return {HEADER_NAME: tenant_id}


# --- create --------------------------------------------------------------------------


def test_create_tenant_happy_path(client: TestClient) -> None:
    response = client.post("/v1/tenants", json=create_payload(), headers=_headers())
    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == TENANT_A
    assert body["namespace"] == "saena-tenant-acme-co"
    assert body["status"] == "active"
    assert body["engine_scope"] == ["chatgpt-search"]
    assert "created_at" in body
    assert "updated_at" in body


def test_create_tenant_namespace_input_rejected(client: TestClient) -> None:
    """`namespace` is a computed field (ADR-0014 Constraints:65) — a request
    body that supplies it fails pydantic's `extra="forbid"` schema check
    (`TenantCreateRequest`, `schemas.py`), which this service maps to a
    distinct `error_code` (task spec: "input namespace REJECTED — computed
    only") rather than the generic validation category."""
    payload = create_payload(namespace="saena-tenant-attacker-supplied")
    response = client.post("/v1/tenants", json=payload, headers=_headers())
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "saena.validation.namespace_input_rejected"
    assert body["retryable"] is False


def test_create_tenant_invalid_slug_returns_400_problem_shape(client: TestClient) -> None:
    payload = create_payload(tenant_id="INVALID_SLUG!!")
    response = client.post("/v1/tenants", json=payload, headers=_headers())
    assert response.status_code == 400
    body = response.json()
    for field in ("type", "title", "status", "error_code", "retryable", "trace_id", "instance"):
        assert field in body, f"missing RFC 9457 field {field!r}"
    assert body["error_code"] == "saena.identity.invalid_tenant_id"
    assert body["retryable"] is False


def test_create_tenant_missing_required_field_generic_validation_problem(
    client: TestClient,
) -> None:
    """A schema violation that is NOT the `namespace`-specific case (e.g. a
    missing required field) falls through to the generic `validation`
    category, distinct from `saena.validation.namespace_input_rejected`."""
    payload = create_payload()
    del payload["display_name"]
    response = client.post("/v1/tenants", json=payload, headers=_headers())
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "saena.validation.schema_mismatch"
    assert body["retryable"] is False


def test_create_tenant_duplicate_returns_conflict(client: TestClient) -> None:
    client.post("/v1/tenants", json=create_payload(), headers=_headers())
    response = client.post("/v1/tenants", json=create_payload(), headers=_headers())
    assert response.status_code == 409
    body = response.json()
    assert body["error_code"] == "saena.conflict.tenant_already_exists"


def test_create_tenant_engine_scope_violation(client: TestClient) -> None:
    payload = create_payload(engine_scope=["google-ai-overviews"])
    response = client.post("/v1/tenants", json=payload, headers=_headers())
    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "saena.policy_denied.engine_scope_violation"
    assert body["retryable"] is False


# --- get / gated read ------------------------------------------------------------------


def test_get_tenant_happy_path(client: TestClient) -> None:
    client.post("/v1/tenants", json=create_payload(), headers=_headers())
    response = client.get(f"/v1/tenants/{TENANT_A}", headers=_headers())
    assert response.status_code == 200
    assert response.json()["tenant_id"] == TENANT_A


def test_get_suspended_tenant_returns_problem(client: TestClient) -> None:
    client.post("/v1/tenants", json=create_payload(), headers=_headers())
    client.post(f"/v1/tenants/{TENANT_A}/status", json={"action": "suspend"}, headers=_headers())
    response = client.get(f"/v1/tenants/{TENANT_A}", headers=_headers())
    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "saena.identity.tenant_suspended"
    assert body["retryable"] is False


def test_get_tenant_not_found(client: TestClient) -> None:
    response = client.get(f"/v1/tenants/{TENANT_A}", headers=_headers())
    assert response.status_code == 404
    assert response.json()["error_code"] == "saena.not_found.resource_missing"


# --- record (gate-free admin view) ------------------------------------------------------


def test_get_record_works_for_suspended_tenant(client: TestClient) -> None:
    client.post("/v1/tenants", json=create_payload(), headers=_headers())
    client.post(f"/v1/tenants/{TENANT_A}/status", json={"action": "suspend"}, headers=_headers())
    response = client.get(f"/v1/tenants/{TENANT_A}/record", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == TENANT_A
    assert body["status"] == "suspended"
    assert body["raw_payload"]["status"] == "suspended"


def test_get_record_not_found(client: TestClient) -> None:
    response = client.get(f"/v1/tenants/{TENANT_A}/record", headers=_headers())
    assert response.status_code == 404


# --- status transitions ------------------------------------------------------------------


def test_suspend_then_reactivate_flow(client: TestClient) -> None:
    client.post("/v1/tenants", json=create_payload(), headers=_headers())

    suspend_resp = client.post(
        f"/v1/tenants/{TENANT_A}/status", json={"action": "suspend"}, headers=_headers()
    )
    assert suspend_resp.status_code == 200
    suspend_body = suspend_resp.json()
    assert suspend_body["previous_status"] == "active"
    assert suspend_body["status"] == "suspended"

    reactivate_resp = client.post(
        f"/v1/tenants/{TENANT_A}/status", json={"action": "reactivate"}, headers=_headers()
    )
    assert reactivate_resp.status_code == 200
    reactivate_body = reactivate_resp.json()
    assert reactivate_body["previous_status"] == "suspended"
    assert reactivate_body["status"] == "active"

    get_resp = client.get(f"/v1/tenants/{TENANT_A}", headers=_headers())
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "active"


def test_invalid_status_transition_returns_conflict(client: TestClient) -> None:
    client.post("/v1/tenants", json=create_payload(), headers=_headers())
    response = client.post(
        f"/v1/tenants/{TENANT_A}/status", json={"action": "reactivate"}, headers=_headers()
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "saena.conflict.invalid_status_transition"


def test_terminate_is_terminal(client: TestClient) -> None:
    client.post("/v1/tenants", json=create_payload(), headers=_headers())
    terminate_resp = client.post(
        f"/v1/tenants/{TENANT_A}/status", json={"action": "terminate"}, headers=_headers()
    )
    assert terminate_resp.status_code == 200
    assert terminate_resp.json()["status"] == "terminating"

    follow_up = client.post(
        f"/v1/tenants/{TENANT_A}/status", json={"action": "reactivate"}, headers=_headers()
    )
    assert follow_up.status_code == 409


# --- header/env mismatch (ADR-0014) -------------------------------------------------------


def test_header_env_mismatch_returns_403(
    repo: InMemoryTenantRepository,
    outbox: InMemoryOutbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TENANT_ENV_VAR_NAME, TENANT_A)
    app = create_app(repo, outbox)
    client = TestClient(app)

    response = client.get(f"/v1/tenants/{TENANT_A}", headers=_headers(TENANT_B))
    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "saena.auth.tenant_mismatch"
    assert body["retryable"] is False


def test_missing_header_on_tenant_scoped_route_returns_403(
    repo: InMemoryTenantRepository,
    outbox: InMemoryOutbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TENANT_ENV_VAR_NAME, TENANT_A)
    app = create_app(repo, outbox)
    client = TestClient(app)

    response = client.get(f"/v1/tenants/{TENANT_A}")
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.auth.tenant_mismatch"


def test_health_route_exempt_from_tenant_reconciliation(
    repo: InMemoryTenantRepository, outbox: InMemoryOutbox
) -> None:
    # No SAENA_TENANT_ID env set at all — /health must still succeed since
    # it is outside TENANT_SCOPED_PATH_PREFIX.
    app = create_app(repo, outbox)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


# --- cross-tenant denial (both directions) ------------------------------------------------


def test_cross_tenant_path_vs_header_denied(client: TestClient) -> None:
    """Header/env agree on TENANT_A, but the path names TENANT_B."""
    client.post("/v1/tenants", json=create_payload(), headers=_headers())
    response = client.get(f"/v1/tenants/{TENANT_B}", headers=_headers(TENANT_A))
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.auth.tenant_mismatch"


def test_cross_tenant_header_vs_path_denied_other_direction(
    repo: InMemoryTenantRepository,
    outbox: InMemoryOutbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Header/env agree on TENANT_B, but the path names TENANT_A —
    the reverse pairing from the test above, proving the guard is symmetric
    and not merely hardcoded to one tenant ordering."""
    monkeypatch.setenv(TENANT_ENV_VAR_NAME, TENANT_B)
    app = create_app(repo, outbox)
    client = TestClient(app)

    response = client.get(f"/v1/tenants/{TENANT_A}", headers=_headers(TENANT_B))
    assert response.status_code == 403
    assert response.json()["error_code"] == "saena.auth.tenant_mismatch"


# --- no stack traces in error bodies -----------------------------------------------------


def _make_invalid_create_response(c: TestClient) -> Any:
    return c.post("/v1/tenants", json=create_payload(tenant_id="BAD SLUG"), headers=_headers())


def _make_not_found_get_response(c: TestClient) -> Any:
    return c.get(f"/v1/tenants/{TENANT_A}", headers=_headers())


def _make_invalid_status_response(c: TestClient) -> Any:
    return c.post(f"/v1/tenants/{TENANT_A}/status", json={"action": "bogus"}, headers=_headers())


@pytest.mark.parametrize(
    "make_response",
    [_make_invalid_create_response, _make_not_found_get_response, _make_invalid_status_response],
)
def test_no_stack_trace_in_error_bodies(client: TestClient, make_response: Any) -> None:
    response = make_response(client)
    assert response.status_code >= 400
    raw_text = response.text
    assert "Traceback" not in raw_text
    assert "saena_tenant_control" not in raw_text
    assert ".py" not in raw_text
    body = response.json()
    assert isinstance(body, dict)
    assert "stack" not in body
    assert "traceback" not in body


def test_unhandled_exception_maps_to_generic_internal_problem(
    repo: InMemoryTenantRepository, outbox: InMemoryOutbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repository that raises an unexpected (non-domain) error must still
    produce a safe, generic RFC 9457 body — never leak the raw exception
    text or a stack trace."""
    monkeypatch.setenv(TENANT_ENV_VAR_NAME, TENANT_A)

    class ExplodingRepository(InMemoryTenantRepository):
        def get_record(self, tenant_id: object) -> object:  # type: ignore[override]
            raise RuntimeError("super secret internal detail: password=hunter2")

    app = create_app(ExplodingRepository(), outbox)
    client = TestClient(app)

    response = client.get(f"/v1/tenants/{TENANT_A}/record", headers=_headers())
    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "saena.internal.unexpected"
    assert "hunter2" not in response.text
    assert "password" not in response.text
    assert "RuntimeError" not in response.text

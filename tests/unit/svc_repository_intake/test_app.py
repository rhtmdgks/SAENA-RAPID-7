"""HTTP-level smoke tests for `saena_repository_intake.app` — proves the
FastAPI adapter wires `core.perform_intake` end-to-end (RFC 9457 error
mapping included), on top of the core-level unit tests in the sibling
`test_*.py` modules."""

from __future__ import annotations

from intake_factories import TENANT_A, TENANT_B, build_job_context, build_snapshot_payload


def _body(**overrides):
    job_context = build_job_context()
    payload = build_snapshot_payload()
    payload["job_context"] = {
        "tenant_id": job_context.tenant_id,
        "workspace_id": job_context.workspace_id,
        "project_id": job_context.project_id,
        "run_id": job_context.run_id,
        "trace_id": job_context.trace_id,
        "idempotency_key": job_context.idempotency_key,
        "actor_id": job_context.actor_id,
    }
    payload.update(overrides)
    return payload


def test_post_intake_accepted_then_replayed(client, tenant_headers):
    body = _body()

    first = client.post("/v1/intake", json=body, headers=tenant_headers)
    assert first.status_code == 201, first.text
    assert first.json()["replayed"] is False
    assert first.json()["manifest"]["decision"] == "accepted"

    second = client.post("/v1/intake", json=body, headers=tenant_headers)
    assert second.status_code == 200, second.text
    assert second.json()["replayed"] is True


def test_post_intake_missing_tenant_header_is_400(client):
    response = client.post("/v1/intake", json=_body())
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")


def test_post_intake_cross_tenant_is_mapped_to_403(client, tenant_headers):
    body = _body()
    body["job_context"]["tenant_id"] = TENANT_A  # header claims TENANT_A
    body["tenant_id"] = TENANT_B  # snapshot claims a DIFFERENT tenant

    response = client.post("/v1/intake", json=body, headers=tenant_headers)
    assert response.status_code == 403
    problem = response.json()
    assert problem["error_code"] == "saena.policy_denied.cross_tenant_source"
    # RFC 9457 problem body never echoes the raw request payload
    assert "content_hash" not in problem


def test_post_intake_inline_content_field_is_422_before_domain_logic(client, tenant_headers):
    body = _body(content_base64="ZmFrZQ==")
    response = client.post("/v1/intake", json=body, headers=tenant_headers)
    assert response.status_code == 422
    problem = response.json()
    # sanitized validation error shape — no `input` echo of the request body
    assert all("input" not in error for error in problem["errors"])

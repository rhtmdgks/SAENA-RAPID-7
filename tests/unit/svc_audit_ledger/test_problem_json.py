"""Every error response is RFC 9457 `application/problem+json`-shaped (ADR-0015)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from ledger_factories import make_append_body, roles_header

_REQUIRED_FIELDS = {"type", "title", "status", "error_code", "retryable", "trace_id"}


def test_rbac_denial_is_problem_json_shaped(client: TestClient) -> None:
    resp = client.post(
        "/v1/audit/entries", json=make_append_body(), headers=roles_header("auditor")
    )

    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body.keys() >= _REQUIRED_FIELDS
    assert body["status"] == 403
    assert body["retryable"] is False
    assert len(body["trace_id"]) == 32


def test_not_found_is_problem_json_shaped(client: TestClient) -> None:
    unknown_ref = "audit:sha256:" + "b" * 64

    resp = client.get(f"/v1/audit/lineage/{unknown_ref}", headers=roles_header("auditor"))

    assert resp.status_code == 404
    body = resp.json()
    assert body.keys() >= _REQUIRED_FIELDS
    assert body["instance"] == f"/v1/audit/lineage/{unknown_ref}"

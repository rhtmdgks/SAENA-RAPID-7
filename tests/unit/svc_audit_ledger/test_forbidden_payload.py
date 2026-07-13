"""Forbidden-data guard enforced at the HTTP boundary — 4xx, never echoes the value."""

from __future__ import annotations

from fastapi.testclient import TestClient
from ledger_factories import make_append_body, roles_header

_SECRET_VALUE = "hunter2-super-secret"


def test_forbidden_password_key_rejected_without_echoing_value(client: TestClient) -> None:
    body = make_append_body(payload={"password": _SECRET_VALUE})

    resp = client.post("/v1/audit/entries", json=body, headers=roles_header("service"))

    assert 400 <= resp.status_code < 500
    raw_text = resp.text
    assert _SECRET_VALUE not in raw_text
    problem = resp.json()
    assert problem["error_code"] == "saena.audit_ledger.forbidden_payload_data"
    assert "password" in problem["detail"]
    assert _SECRET_VALUE not in problem["detail"]


def test_forbidden_stack_trace_value_rejected_without_echoing_value(client: TestClient) -> None:
    traceback_text = (
        "Traceback (most recent call last):\n"
        '  File "app.py", line 12, in handler\n'
        "    raise ValueError('boom')\nValueError: boom"
    )
    body = make_append_body(payload={"note": traceback_text})

    resp = client.post("/v1/audit/entries", json=body, headers=roles_header("service"))

    assert 400 <= resp.status_code < 500
    assert traceback_text not in resp.text
    assert "boom" not in resp.text


def test_forbidden_payload_does_not_enter_the_ledger(client: TestClient) -> None:
    body = make_append_body(payload={"secret": "abc123"})
    client.post("/v1/audit/entries", json=body, headers=roles_header("service"))

    resp = client.get(
        "/v1/audit/entries",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": body["tenant_id"]},
    )

    assert resp.json()["entries"] == []

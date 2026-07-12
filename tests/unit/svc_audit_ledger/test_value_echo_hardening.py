"""Critic MUST-FIX 1/2 (w2-10 review): no raw value ever leaks through an error response.

MUST-FIX 1 — FastAPI's default `RequestValidationError`/unhandled-exception
handlers echo the raw caller-supplied value (`input` field / stack trace).
This module proves the replacement handlers (`app.py`
`_request_validation_error_handler`/`_unhandled_exception_handler`,
`problem.py` `validation_error_problem`/`internal_error_problem`) never do.

MUST-FIX 2 — `AppendEntryRequest.error_code` was unguarded free text
(`build_entry` only guards `payload`/`actor`). This module proves the
boundary guard (`guard_payload({"error_code": ...})` in `app.py`'s
`append_entry` handler, before `build_entry` is called) rejects
guard-detectable forbidden content in `error_code` without echoing it.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from ledger_factories import make_append_body, roles_header
from saena_audit_ledger import create_app
from saena_domain.audit import AuditEntry
from saena_domain.identity import TenantId

_SECRET_VALUE = "MY_SECRET_VALUE_123"


def test_wrong_type_body_is_problem_json_without_echoing_the_value(client: TestClient) -> None:
    """A structurally wrong-type request body (`payload` as a bare string,
    every other required field missing) triggers FastAPI's own
    `RequestValidationError` — the raw string must never appear in the
    response, and the response must be problem+json, not plain json."""
    resp = client.post(
        "/v1/audit/entries", json={"payload": _SECRET_VALUE}, headers=roles_header("service")
    )

    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert _SECRET_VALUE not in resp.text
    body = resp.json()
    assert body["error_code"] == "saena.audit_ledger.validation_failed"
    assert isinstance(body["errors"], list)
    for error in body["errors"]:
        assert set(error.keys()) <= {"type", "loc", "msg"}


def test_unexpected_exception_is_500_problem_json_without_stack_trace() -> None:
    """An unanticipated exception from the injected `AuditLedgerPort` (never
    a `saena_domain` structured error, never `ForbiddenAuditDataError`) is
    mapped to a bare 500 problem+json body — no exception message, type
    name, or traceback text reaches the caller."""

    class _ExplodingLedger:
        def append(self, entry: AuditEntry) -> AuditEntry:  # pragma: no cover
            raise RuntimeError("boom internal secret trace /etc/passwd")

        def read_range(
            self,
            *,
            tenant_id: TenantId | None = None,
            start_index: int = 0,
            end_index: int | None = None,
        ) -> tuple[AuditEntry, ...]:
            raise RuntimeError("boom internal secret trace /etc/passwd")

        def verify(self, *, tenant_id: TenantId | None = None) -> tuple[bool, int | None]:
            raise RuntimeError("boom internal secret trace /etc/passwd")

    # raise_server_exceptions=False: TestClient's default behavior
    # re-raises the server-side exception into the test process (a
    # debugging aid) rather than returning the actual HTTP response — this
    # test is specifically about what a REAL client over the wire receives,
    # so it must observe the rendered response instead.
    exploding_client = TestClient(
        create_app(_ExplodingLedger()),  # type: ignore[arg-type]
        raise_server_exceptions=False,
    )

    resp = exploding_client.get(
        "/v1/audit/entries",
        headers={**roles_header("auditor"), "X-Saena-Tenant-Id": "acme-co"},
    )

    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert "boom" not in resp.text
    assert "secret" not in resp.text
    assert "Traceback" not in resp.text
    assert "RuntimeError" not in resp.text
    body: dict[str, Any] = resp.json()
    assert body["error_code"] == "saena.audit_ledger.internal_error"
    assert body["status"] == 500


def test_error_code_with_stack_trace_content_is_rejected_without_echo(
    client: TestClient,
) -> None:
    traceback_text = (
        "Traceback (most recent call last):\n"
        '  File "app.py", line 12, in handler\n'
        "    raise ValueError('boom')\nValueError: boom"
    )
    body = make_append_body(error_code=traceback_text)

    resp = client.post("/v1/audit/entries", json=body, headers=roles_header("service"))

    assert 400 <= resp.status_code < 500
    assert traceback_text not in resp.text
    assert "boom" not in resp.text
    problem = resp.json()
    assert problem["error_code"] == "saena.audit_ledger.forbidden_payload_data"
    assert "error_code" in problem["detail"]


def test_error_code_with_password_pattern_is_rejected_without_echo(client: TestClient) -> None:
    """`error_code="password=hunter2"` fails `AuditEntry`'s own
    `^saena\\.[a-z_]+\\.[a-z_]+$` pattern — a DIFFERENT rejection path than
    the guard (the guard's documented gap: free-text `password=` content is
    not itself a guard-detectable pattern, see `saena_domain.audit.guard`
    module docstring), but the value must still never be echoed, now that
    the `ValidationError` branch routes through `validation_error_problem`
    instead of `str(exc)`."""
    secret_value = "password=hunter2"
    body = make_append_body(error_code=secret_value)

    resp = client.post("/v1/audit/entries", json=body, headers=roles_header("service"))

    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert secret_value not in resp.text
    assert "hunter2" not in resp.text
    problem = resp.json()
    assert problem["error_code"] == "saena.audit_ledger.validation_failed"


def test_error_code_without_forbidden_content_is_accepted(client: TestClient) -> None:
    body = make_append_body(error_code="saena.audit_ledger.example_error")

    resp = client.post("/v1/audit/entries", json=body, headers=roles_header("service"))

    assert resp.status_code == 201
    assert resp.json()["error_code"] == "saena.audit_ledger.example_error"

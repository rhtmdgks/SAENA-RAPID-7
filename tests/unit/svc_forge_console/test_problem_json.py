"""RFC 9457 `problem+json` response shape (ADR-0015) — covers FastAPI's own
422 request-validation path and human-actor-without-tenant rejection."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from saena_forge_console.app import create_app
from saena_schemas.common.problem_detail_v1 import ProblemDetail

from svc_forge_console.conftest import DEFAULT_TENANT, actor_headers, run_create_body

_SENTINEL_SECRET = "sk-live-SENTINEL-SECRET-value-9f8e7d6c5b4a"


def _assert_valid_problem_detail(body: dict[str, object]) -> None:
    # Round-trips through the generated ProblemDetail model -- proves the
    # body is not just "looks like RFC 9457" but is actually schema-valid
    # against the same contract every other service would validate against.
    ProblemDetail.model_validate(body)


class TestValidationErrorShape:
    def test_malformed_body_returns_422_problem_json(self, client: TestClient) -> None:
        response = client.post(
            "/v1/runs",
            json={"state": "not-a-real-state", "base_commit": "a" * 40},
            headers=actor_headers(roles="proposer"),
        )
        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"
        body = response.json()
        _assert_valid_problem_detail(body)
        assert body["error_code"] == "saena.validation.schema_mismatch"
        assert body["status"] == 422
        assert body["retryable"] is False
        assert "trace_id" in body

    def test_missing_required_field_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/v1/runs",
            json={"state": "INTAKE"},
            headers=actor_headers(roles="proposer"),
        )
        assert response.status_code == 422
        _assert_valid_problem_detail(response.json())

    def test_extra_field_is_rejected_extra_forbid(self, client: TestClient) -> None:
        response = client.post(
            "/v1/runs",
            json=run_create_body(unexpected_field="nope"),
            headers=actor_headers(roles="proposer"),
        )
        assert response.status_code == 422

    def test_invalid_field_value_is_absent_from_response_and_logs(self, client: TestClient) -> None:
        """MUST-FIX 1 (critic): `RequestValidationError.errors()` carries the
        raw offending value under an `"input"` key -- a naive
        `detail=str(exc.errors())` would round-trip a secret-shaped
        submitted value straight back into the problem+json body. Assert the
        sentinel is absent from BOTH the response text and every emitted log
        line for this request.
        """
        logger = logging.getLogger("saena_forge_console.app")
        captured: list[str] = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(self.format(record))

        capture_handler = _CaptureHandler()
        existing_formatter = next(
            (h.formatter for h in logger.handlers if h.formatter is not None), None
        )
        if existing_formatter is not None:
            capture_handler.setFormatter(existing_formatter)
        logger.addHandler(capture_handler)
        try:
            response = client.post(
                "/v1/runs",
                json={
                    "state": "INTAKE",
                    "base_commit": _SENTINEL_SECRET,
                    "human_approval_required": True,
                },
                headers=actor_headers(roles="proposer"),
            )
        finally:
            logger.removeHandler(capture_handler)

        assert response.status_code == 422
        assert _SENTINEL_SECRET not in response.text
        for line in captured:
            assert _SENTINEL_SECRET not in line
        # Body carries only the fixed, non-echoing detail string.
        assert response.json()["detail"] == "request body failed schema validation"


class TestProblemJsonEverySeenErrorCategory:
    def test_403_permission_denied_is_valid_problem_detail(self, client: TestClient) -> None:
        response = client.post(
            "/v1/runs", json=run_create_body(), headers=actor_headers(roles=None)
        )
        _assert_valid_problem_detail(response.json())

    def test_404_not_found_is_valid_problem_detail(self, client: TestClient) -> None:
        response = client.get(
            "/v1/runs/019f5769-b226-7e4c-a6f7-6e0fa4c5ef56",
            headers=actor_headers(roles="proposer"),
        )
        _assert_valid_problem_detail(response.json())

    def test_401_auth_error_is_valid_problem_detail(self, client: TestClient) -> None:
        headers = actor_headers(roles=None)
        del headers["X-Saena-Session-Id"]
        response = client.get("/v1/actor/whoami", headers=headers)
        _assert_valid_problem_detail(response.json())


class TestHumanActorWithoutTenantRejected:
    def test_human_actor_without_tenant_id_is_rejected(self, client: TestClient) -> None:
        headers = actor_headers(actor_type="human", tenant_id=None, roles=None)
        response = client.get("/v1/actor/whoami", headers=headers)
        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == "saena.validation.actor_tenant_required"

    def test_system_actor_without_tenant_id_is_accepted(self, client: TestClient) -> None:
        headers = actor_headers(actor_type="system", tenant_id=None, roles=None)
        response = client.get("/v1/actor/whoami", headers=headers)
        assert response.status_code == 200


class TestGenericExceptionHandler:
    """MUST-FIX 2 (critic): a genuine bug (not a `ServiceError`) must still
    produce a `problem+json` 500 -- never Starlette's default plaintext
    500, and never a stack trace / exception message in the body.
    """

    def test_unexpected_exception_returns_500_problem_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAENA_TENANT_ID", DEFAULT_TENANT)
        sentinel = "leak-me-if-you-can-RCE-detail-12345"

        class _BoomLineagePort:
            def resolve(self, tenant_id: str, ref: str) -> dict[str, object]:
                raise RuntimeError(sentinel)

        app = create_app(lineage_port=_BoomLineagePort())
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/v1/lineage/audit:sha256:" + "a" * 64,
            headers=actor_headers(tenant_id=DEFAULT_TENANT, roles="auditor"),
        )
        assert response.status_code == 500
        assert response.headers["content-type"] == "application/problem+json"
        _assert_valid_problem_detail(response.json())
        body = response.json()
        assert body["error_code"] == "saena.internal.unexpected"
        assert sentinel not in response.text
        assert "Traceback" not in response.text
        assert "RuntimeError" not in response.text

    def test_unexpected_exception_not_logged_with_raw_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAENA_TENANT_ID", DEFAULT_TENANT)
        sentinel = "leak-me-if-you-can-log-detail-67890"

        class _BoomLineagePort:
            def resolve(self, tenant_id: str, ref: str) -> dict[str, object]:
                raise RuntimeError(sentinel)

        app = create_app(lineage_port=_BoomLineagePort())
        client = TestClient(app, raise_server_exceptions=False)

        logger = logging.getLogger("saena_forge_console.app")
        captured: list[str] = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(self.format(record))

        capture_handler = _CaptureHandler()
        existing_formatter = next(
            (h.formatter for h in logger.handlers if h.formatter is not None), None
        )
        if existing_formatter is not None:
            capture_handler.setFormatter(existing_formatter)
        logger.addHandler(capture_handler)
        try:
            client.get(
                "/v1/lineage/audit:sha256:" + "a" * 64,
                headers=actor_headers(tenant_id=DEFAULT_TENANT, roles="auditor"),
            )
        finally:
            logger.removeHandler(capture_handler)

        for line in captured:
            assert sentinel not in line
            assert "Traceback" not in line

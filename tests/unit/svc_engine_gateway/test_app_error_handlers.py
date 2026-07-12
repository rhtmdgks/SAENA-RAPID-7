"""`_validation_error_handler` / `_unhandled_exception_handler` — RFC 9457
422/500 handlers that never echo request-derived values (critic MUST-FIX 1).

FastAPI's *default* `RequestValidationError` handler returns bare
`{"detail": [...]}` (not `application/problem+json`) and echoes the raw
rejected value via each error's `input` key — this module proves that leak
is closed and every error response coming out of this app, including
framework-raised and fully unanticipated ones, is genuinely RFC 9457
`application/problem+json` with no value/stack-trace echo.
"""

from __future__ import annotations

import pytest
from conftest import TENANT_HEADERS
from fastapi import FastAPI
from fastapi.testclient import TestClient
from saena_engine_gateway.app import create_app
from saena_engine_gateway.flags import FlagRegistry
from saena_engine_gateway.registry import AdapterRegistry

_SENTINEL = "SENTINEL_VALUE_MUST_NOT_LEAK_998877_xyz"


class _BoomAdapter:
    """Adapter whose stub call always raises, to exercise the generic
    unhandled-exception handler deterministically."""

    @property
    def engine_id(self) -> str:
        return "chatgpt-search"

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset()

    def submit_observation_request(self, request: dict[str, object]) -> dict[str, object]:
        raise RuntimeError(_SENTINEL)


def _boom_app() -> FastAPI:
    registry = AdapterRegistry()
    registry.register(_BoomAdapter())
    flags = FlagRegistry()
    flags.create("chatgpt-search", enabled=True)
    return create_app(registry=registry, flags=flags)


class TestValidationErrorHandlerNoValueLeak:
    def test_non_string_engine_id_sentinel_absent_from_response(self, client: TestClient) -> None:
        # A string value passes pydantic's str-type check regardless of
        # content, so the sentinel is nested inside a non-string structure
        # here to actually exercise validation rejection.
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"engine_id": [_SENTINEL, "nested"]},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 422
        assert _SENTINEL not in response.text

    def test_int_engine_id_sentinel_absent_from_response(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"engine_id": 4242424242},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 422
        assert "4242424242" not in response.text

    def test_dict_engine_id_sentinel_absent_from_response(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"engine_id": {"leak": _SENTINEL}},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 422
        assert _SENTINEL not in response.text


class TestValidationErrorHandlerShape:
    def test_content_type_is_problem_json(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"engine_id": 123},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

    def test_body_has_rfc9457_required_fields(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"engine_id": 123},
            headers=TENANT_HEADERS,
        )
        body = response.json()
        for field in ("type", "title", "status", "error_code", "retryable", "trace_id"):
            assert field in body
        assert body["status"] == 422
        assert body["error_code"] == "saena.validation.request_validation_failed"

    def test_detail_is_a_fixed_string_not_value_derived(self, client: TestClient) -> None:
        first = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"engine_id": 111},
            headers=TENANT_HEADERS,
        ).json()
        second = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"engine_id": 222},
            headers=TENANT_HEADERS,
        ).json()
        assert first["detail"] == second["detail"]

    def test_sanitized_errors_carry_only_loc_type_msg(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"engine_id": 123},
            headers=TENANT_HEADERS,
        )
        body = response.json()
        assert "errors" in body
        assert len(body["errors"]) >= 1
        for error in body["errors"]:
            assert set(error.keys()) == {"type", "loc", "msg"}
            assert "input" not in error
            assert "ctx" not in error


class TestUnhandledExceptionHandlerNoLeak:
    def test_sentinel_message_absent_from_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAENA_TENANT_ID", "acme-corp")
        client = TestClient(_boom_app(), raise_server_exceptions=False)
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 500
        assert _SENTINEL not in response.text
        assert "RuntimeError" not in response.text
        assert "Traceback" not in response.text

    def test_content_type_is_problem_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAENA_TENANT_ID", "acme-corp")
        client = TestClient(_boom_app(), raise_server_exceptions=False)
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={},
            headers=TENANT_HEADERS,
        )
        assert response.headers["content-type"] == "application/problem+json"

    def test_body_has_rfc9457_required_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAENA_TENANT_ID", "acme-corp")
        client = TestClient(_boom_app(), raise_server_exceptions=False)
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={},
            headers=TENANT_HEADERS,
        )
        body = response.json()
        for field in ("type", "title", "status", "error_code", "retryable", "trace_id"):
            assert field in body
        assert body["status"] == 500
        assert body["error_code"] == "saena.internal.unexpected"
        assert body["detail"] == "an unexpected error occurred"


class TestEngineGatewayErrorsStillUnaffected:
    """The generic `Exception` handler must not shadow the more specific
    `EngineGatewayError` handler FastAPI already had (handler specificity
    ordering) -- these paths must keep their own RFC 9457 shape/status."""

    def test_engine_not_permitted_still_403(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/gemini/requests",
            json={},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "saena.policy_denied.engine_not_permitted"

    def test_payload_mismatch_still_400(self, client: TestClient) -> None:
        response = client.post(
            "/v1/engines/chatgpt-search/requests",
            json={"engine_id": "gemini"},
            headers=TENANT_HEADERS,
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == "saena.validation.engine_id_mismatch"

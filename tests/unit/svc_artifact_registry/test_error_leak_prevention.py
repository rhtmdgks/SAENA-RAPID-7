"""Critic MUST-FIX/SHOULD-FIX (w2-16 review): FastAPI's default 422 handler
echoes the raw request body — including `blob_base64` customer-source diff
content, MAX sensitivity (contract-catalog.md PatchArtifact "diff=소스") —
back to the client. This module proves the sentinel value is absent from
BOTH the HTTP response and the logs for every path that can reach a 422,
and that an unhandled exception never leaks its message either."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient
from registry_factories import build_register_request

SENTINEL = "SENTINEL_CUSTOMER_SOURCE_DIFF_CONTENT_do-not-echo-me"


def _capture_logs() -> tuple[logging.Handler, list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record)  # type: ignore[method-assign]
    return handler, records


def test_malformed_manifest_field_422_does_not_echo_blob_base64(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    """`manifest` itself malformed (not a dict) — the historical FastAPI
    default handler would still echo the WHOLE body's offending values,
    including a sibling field's value in some pydantic-core error shapes."""
    logger = logging.getLogger("saena_artifact_registry")
    handler, records = _capture_logs()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        response = client.post(
            "/v1/artifacts",
            json={"manifest": "not-a-dict", "blob_base64": SENTINEL},
            headers=tenant_headers,
        )
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 422
    assert SENTINEL not in response.text
    for record in records:
        assert SENTINEL not in record.getMessage()
        for value in getattr(record, "saena_attributes", {}).values():
            assert SENTINEL not in str(value)


def test_blob_base64_field_itself_invalid_422_does_not_echo_value(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    """The validation error is directly ON `blob_base64` (wrong type) — the
    highest-risk case, since FastAPI's default `input` echo would place the
    sentinel value directly under `errors[i]["input"]`."""
    logger = logging.getLogger("saena_artifact_registry")
    handler, records = _capture_logs()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        request_body = build_register_request()
        request_body["blob_base64"] = {"nested": SENTINEL}  # wrong type: dict, not str
        response = client.post("/v1/artifacts", json=request_body, headers=tenant_headers)
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 422
    assert SENTINEL not in response.text
    for record in records:
        assert SENTINEL not in record.getMessage()
        for value in getattr(record, "saena_attributes", {}).values():
            assert SENTINEL not in str(value)


def test_validation_error_response_is_problem_json_with_sanitized_errors(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    response = client.post(
        "/v1/artifacts",
        json={"manifest": "not-a-dict", "blob_base64": "irrelevant"},
        headers=tenant_headers,
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["error_code"] == "saena.validation.request_body_invalid"
    assert "errors" in body
    for error in body["errors"]:
        assert set(error.keys()) == {"loc", "type", "msg"}


def test_extra_forbidden_field_422_does_not_echo_value(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    """`extra="forbid"` rejection also carries an `input` in FastAPI's
    default shape — confirm the sanitized handler strips it here too."""
    request_body = build_register_request()
    request_body["manifest"]["unexpected_extra_field"] = SENTINEL

    response = client.post("/v1/artifacts", json=request_body, headers=tenant_headers)

    assert response.status_code == 422
    assert SENTINEL not in response.text


def test_unhandled_exception_maps_to_rfc9457_500_without_leaking_message(
    tenant_headers: dict[str, str],
) -> None:
    from saena_artifact_registry import InMemoryBlobStore, create_app

    class _BoomManifestPort:
        def get(self, tenant_id: object, patch_unit_id: str, worktree_commit: str) -> dict:
            raise RuntimeError(f"boom: {SENTINEL}")

        def put(self, *args: object, **kwargs: object) -> dict:
            raise RuntimeError(f"boom: {SENTINEL}")

    logger = logging.getLogger("saena_artifact_registry")
    handler, records = _capture_logs()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        app = create_app(_BoomManifestPort(), InMemoryBlobStore())  # type: ignore[arg-type]
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/artifacts/some-unit/deadbeef", headers=tenant_headers)
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["error_code"] == "saena.internal.unexpected"
    assert body["detail"] == "an unexpected error occurred"
    assert SENTINEL not in response.text
    assert "RuntimeError" not in response.text
    for record in records:
        assert SENTINEL not in record.getMessage()
        for value in getattr(record, "saena_attributes", {}).values():
            assert SENTINEL not in str(value)

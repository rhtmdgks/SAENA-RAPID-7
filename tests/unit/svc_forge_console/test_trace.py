"""W3C `traceparent` propagation into response headers and structured logs
(ADR-0016 correlation), and generation when the caller sends none."""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient
from saena_observability.trace import parse_traceparent

from svc_forge_console.conftest import actor_headers


def test_traceparent_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/v1/actor/whoami", headers=actor_headers(roles=None))
    assert response.status_code == 200
    header = response.headers["traceparent"]
    parsed = parse_traceparent(header)
    assert parsed.version == "00"


def test_inbound_traceparent_trace_id_is_propagated_to_response(client: TestClient) -> None:
    inbound = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    headers = actor_headers(roles=None)
    headers["traceparent"] = inbound
    response = client.get("/v1/actor/whoami", headers=headers)
    outbound = parse_traceparent(response.headers["traceparent"])
    assert outbound.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_malformed_traceparent_does_not_crash_and_generates_a_new_one(
    client: TestClient,
) -> None:
    headers = actor_headers(roles=None)
    headers["traceparent"] = "not-a-valid-traceparent"
    response = client.get("/v1/actor/whoami", headers=headers)
    assert response.status_code == 200
    parsed = parse_traceparent(response.headers["traceparent"])
    assert parsed.version == "00"


def test_error_response_trace_id_matches_response_header(client: TestClient) -> None:
    headers = actor_headers(roles=None)
    del headers["X-Saena-Actor-Id"]
    response = client.get("/v1/actor/whoami", headers=headers)
    assert response.status_code == 401
    body_trace_id = response.json()["trace_id"]
    header_trace_id = parse_traceparent(response.headers["traceparent"]).trace_id
    assert body_trace_id == header_trace_id


def test_request_error_log_line_is_single_line_json(client: TestClient) -> None:
    """The `_problem_response` log line (`saena_forge_console.app`) is
    single-line structured JSON carrying `saena.error_code` — captured here
    by attaching a raw `logging.Handler` (bypassing pytest's `caplog`, which
    intercepts records BEFORE this service's own `SaenaJsonFormatter` runs,
    so `caplog.text` would show the unformatted message, not the JSON line
    under test).
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
        headers = actor_headers(roles=None)
        del headers["X-Saena-Actor-Id"]
        client.get("/v1/actor/whoami", headers=headers)
    finally:
        logger.removeHandler(capture_handler)

    assert len(captured) == 1
    line = captured[0]
    assert "\n" not in line
    parsed = json.loads(line)
    assert "saena.auth.actor_id_required" in parsed["body"]

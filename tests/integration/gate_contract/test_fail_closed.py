"""Fail-closed contract (ADR-0003 / security-model.md): a broken/unreachable
policy-gate never resolves to an implicit allow — `HttpPolicyGateClient`
raises `PolicyGateUnavailableError` for every failure shape, using the REAL
client wired against apps that are up-but-broken, down, or missing entirely.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gate_contract_factories import make_request
from saena_plan_contract.errors import PolicyGateUnavailableError
from saena_plan_contract.gate_client import HttpPolicyGateClient


def _broken_gate_app() -> FastAPI:
    """A policy-gate-SHAPED app whose real route always raises — "the
    process is up but every request fails" fail-closed shape."""
    app = FastAPI(title="broken-policy-gate")

    @app.post("/v1/gate/plan-check")
    async def _broken_plan_check() -> None:
        raise RuntimeError("simulated policy-gate outage")

    @app.get("/v1/health")
    async def _broken_health() -> None:
        raise RuntimeError("simulated policy-gate outage")

    return app


def test_broken_gate_app_is_gate_unavailable_not_allow() -> None:
    app = _broken_gate_app()
    transport_client = TestClient(app, base_url="http://policy-gate", raise_server_exceptions=False)
    client = HttpPolicyGateClient("http://policy-gate", client=transport_client, timeout=5.0)

    with pytest.raises(PolicyGateUnavailableError):
        client.plan_check(make_request(contract_hash="sha256:" + "8" * 64))

    client.close()


def test_completely_missing_app_404s_and_is_gate_unavailable() -> None:
    """No `/v1/gate/plan-check` route registered at all (an app that isn't
    policy-gate-service) — every call 404s, still fail-closed."""
    empty_app = FastAPI(title="not-policy-gate")
    transport_client = TestClient(empty_app, base_url="http://policy-gate")
    client = HttpPolicyGateClient("http://policy-gate", client=transport_client, timeout=5.0)

    with pytest.raises(PolicyGateUnavailableError):
        client.plan_check(make_request(contract_hash="sha256:" + "9" * 64))

    assert client.health() is False
    client.close()


def test_transport_error_against_real_gate_shape_is_gate_unavailable() -> None:
    """A transport-level failure (connection refused) reaching a
    policy-gate-shaped URL — the REAL client's fail-closed branch, exercised
    through a raising `httpx.MockTransport` rather than the in-process ASGI
    app (proves the transport-error path independently of the ASGI-wired
    happy-path tests)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    client = HttpPolicyGateClient(
        "http://policy-gate", client=httpx.Client(transport=transport), timeout=5.0
    )

    with pytest.raises(PolicyGateUnavailableError):
        client.plan_check(make_request(contract_hash="sha256:" + "0" * 64))

    client.close()

"""`TenantReconciliationMiddleware` — ADR-0014 synchronous HTTP guard."""

from __future__ import annotations

import pytest
from conftest import TENANT_HEADERS
from fastapi.testclient import TestClient
from saena_engine_gateway.app import create_app
from saena_engine_gateway.flags import FlagRegistry
from saena_engine_gateway.registry import AdapterRegistry


def _app() -> TestClient:
    registry = AdapterRegistry()
    from saena_engine_gateway.adapters.chatgpt_search import ChatGPTSearchAdapter

    registry.register(ChatGPTSearchAdapter())
    flags = FlagRegistry()
    flags.create("chatgpt-search", enabled=True)
    return TestClient(create_app(registry=registry, flags=flags))


class TestMismatchRejected:
    def test_missing_header_rejected_with_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAENA_TENANT_ID", "acme-corp")
        client = _app()
        response = client.post("/v1/engines/chatgpt-search/requests", json={})
        assert response.status_code == 403
        body = response.json()
        assert body["error_code"] == "saena.identity.tenant_mismatch"
        assert body["type"].endswith("saena.identity.tenant_mismatch")

    def test_missing_env_rejected_with_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAENA_TENANT_ID", raising=False)
        client = _app()
        response = client.post(
            "/v1/engines/chatgpt-search/requests", json={}, headers=TENANT_HEADERS
        )
        assert response.status_code == 403

    def test_disagreeing_values_rejected_with_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAENA_TENANT_ID", "other-corp")
        client = _app()
        response = client.post(
            "/v1/engines/chatgpt-search/requests", json={}, headers=TENANT_HEADERS
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "saena.identity.tenant_mismatch"

    def test_never_returns_200_on_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ADR-0014 Constraints:64 -- mismatch must never silently pass."""
        monkeypatch.setenv("SAENA_TENANT_ID", "other-corp")
        client = _app()
        response = client.post(
            "/v1/engines/chatgpt-search/requests", json={}, headers=TENANT_HEADERS
        )
        assert response.status_code != 200
        assert response.status_code != 202


class TestMatchAccepted:
    def test_matching_header_and_env_proceeds_to_route(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAENA_TENANT_ID", "acme-corp")
        client = _app()
        response = client.post(
            "/v1/engines/chatgpt-search/requests", json={}, headers=TENANT_HEADERS
        )
        assert response.status_code == 202


class TestExemptPaths:
    def test_preflight_exempt_from_tenant_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAENA_TENANT_ID", raising=False)
        client = _app()
        response = client.get("/v1/preflight")
        assert response.status_code == 200

    def test_engines_list_exempt_from_tenant_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAENA_TENANT_ID", raising=False)
        client = _app()
        response = client.get("/v1/engines")
        assert response.status_code == 200

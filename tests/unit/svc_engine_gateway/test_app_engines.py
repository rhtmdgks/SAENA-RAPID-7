"""`GET /v1/engines` — enum-bound, enabled adapters only."""

from __future__ import annotations

from fastapi.testclient import TestClient
from saena_engine_gateway.app import create_app
from saena_engine_gateway.flags import FlagRegistry
from saena_engine_gateway.registry import AdapterRegistry


class TestListEngines:
    def test_returns_chatgpt_search_when_registered_and_enabled(self, client: TestClient) -> None:
        response = client.get("/v1/engines")
        assert response.status_code == 200
        assert response.json() == {"engines": ["chatgpt-search"]}

    def test_returns_empty_list_when_registry_is_empty(self, empty_client: TestClient) -> None:
        response = empty_client.get("/v1/engines")
        assert response.status_code == 200
        assert response.json() == {"engines": []}

    def test_registered_but_flag_off_is_omitted(self, flag_off_client: TestClient) -> None:
        response = flag_off_client.get("/v1/engines")
        assert response.status_code == 200
        assert response.json() == {"engines": []}

    def test_is_reachable_without_a_tenant_header(self) -> None:
        # No SAENA_TENANT_ID bound, no X-Saena-Tenant-Id header — /v1/engines
        # is tenant-exempt metadata (tenant_middleware._TENANT_EXEMPT_PATHS).
        app = create_app(registry=AdapterRegistry(), flags=FlagRegistry())
        response = TestClient(app).get("/v1/engines")
        assert response.status_code == 200

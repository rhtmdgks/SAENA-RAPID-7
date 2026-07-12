"""`GET /v1/preflight` — gateway self-check (k3s spec §8.1 preflight flavor)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from saena_engine_gateway.adapters.chatgpt_search import ChatGPTSearchAdapter
from saena_engine_gateway.app import create_app
from saena_engine_gateway.flags import AdapterFlag, FlagRegistry
from saena_engine_gateway.registry import AdapterRegistry


class RogueAdapter:
    """Adapter-shaped object claiming a non-enum `engine_id`, injected only
    via `AdapterRegistry._unsafe_insert_for_testing` (never `register()`,
    which would itself reject it)."""

    def __init__(self, engine_id: str) -> None:
        self._engine_id = engine_id

    @property
    def engine_id(self) -> str:
        return self._engine_id

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset()

    def submit_observation_request(self, request: dict[str, object]) -> dict[str, object]:
        return {}


class TestPreflightPass:
    def test_v1_standard_setup_passes(self, client: TestClient) -> None:
        response = client.get("/v1/preflight")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "PASS"
        assert body["permitted_engine_ids"] == ["chatgpt-search"]
        assert body["rogue_engine_ids"] == []

    def test_empty_registry_passes(self, empty_client: TestClient) -> None:
        response = empty_client.get("/v1/preflight")
        assert response.json()["status"] == "PASS"

    def test_reachable_without_a_tenant_header(self) -> None:
        app = create_app(registry=AdapterRegistry(), flags=FlagRegistry())
        response = TestClient(app).get("/v1/preflight")
        assert response.status_code == 200


class TestPreflightDetectsRogueAdapter:
    def test_rogue_adapter_bypassing_register_causes_fail(self) -> None:
        registry = AdapterRegistry()
        registry.register(ChatGPTSearchAdapter())
        # Bypass AdapterRegistry.register()'s own EngineNotPermittedError
        # guard entirely -- this is the "inject rogue adapter via registry
        # internals to prove detection" scenario the task spec requires.
        registry._unsafe_insert_for_testing("gemini", RogueAdapter("gemini"))

        flags = FlagRegistry()
        flags.create("chatgpt-search", enabled=True)

        app = create_app(registry=registry, flags=flags)
        response = TestClient(app).get("/v1/preflight")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "FAIL"
        assert "gemini" in body["rogue_engine_ids"]


class TestPreflightDetectsRogueFlag:
    def test_rogue_flag_bypassing_create_causes_fail(self) -> None:
        flags = FlagRegistry()
        flags.create("chatgpt-search", enabled=True)
        # Bypass FlagRegistry.create()'s own EngineNotPermittedError guard.
        flags._unsafe_insert_for_testing(AdapterFlag(engine_id="google-ai-mode", enabled=True))

        app = create_app(registry=AdapterRegistry(), flags=flags)
        response = TestClient(app).get("/v1/preflight")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "FAIL"
        assert "google-ai-mode" in body["rogue_engine_ids"]

    def test_rogue_flag_that_is_disabled_still_fails_preflight(self) -> None:
        """k3s spec §8.1: 'engine flags include any Google AI service in
        v1' is itself the FAIL condition -- presence, not enabled-ness."""
        flags = FlagRegistry()
        flags._unsafe_insert_for_testing(AdapterFlag(engine_id="gemini", enabled=False))

        app = create_app(registry=AdapterRegistry(), flags=flags)
        response = TestClient(app).get("/v1/preflight")

        assert response.json()["status"] == "FAIL"

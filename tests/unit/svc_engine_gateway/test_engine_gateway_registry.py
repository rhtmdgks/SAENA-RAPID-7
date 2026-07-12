"""`AdapterRegistry` — construction-time closed-enum validation (ADR-0001)."""

from __future__ import annotations

import pytest
from saena_engine_gateway.adapters.chatgpt_search import ChatGPTSearchAdapter
from saena_engine_gateway.errors import AdapterNotFoundError, EngineNotPermittedError
from saena_engine_gateway.registry import PERMITTED_ENGINE_IDS, AdapterRegistry


class FakeAdapter:
    """Minimal `EngineAdapter`-shaped stand-in for a rejected `engine_id`."""

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


class TestPermittedEngineIds:
    def test_v1_closed_enum_is_exactly_chatgpt_search(self) -> None:
        assert frozenset({"chatgpt-search"}) == PERMITTED_ENGINE_IDS


class TestRegisterAcceptsPermittedEngine:
    def test_register_chatgpt_search_succeeds(self) -> None:
        registry = AdapterRegistry()
        registry.register(ChatGPTSearchAdapter())
        assert "chatgpt-search" in registry
        assert registry.enabled_engine_ids() == ("chatgpt-search",)

    def test_get_returns_the_registered_adapter(self) -> None:
        registry = AdapterRegistry()
        adapter = ChatGPTSearchAdapter()
        registry.register(adapter)
        assert registry.get("chatgpt-search") is adapter


@pytest.mark.parametrize(
    "rogue_engine_id",
    [
        "google-ai-overviews",
        "google-ai-mode",
        "gemini",
        "google",
        "bard",
        "chatgpt",  # not the exact enum value
        "",
        "google-generative-search",
    ],
)
class TestRegisterRejectsNonEnumEngine:
    def test_register_raises_engine_not_permitted(self, rogue_engine_id: str) -> None:
        registry = AdapterRegistry()
        with pytest.raises(EngineNotPermittedError) as exc_info:
            registry.register(FakeAdapter(rogue_engine_id))
        assert exc_info.value.engine_id == rogue_engine_id
        assert exc_info.value.error_code == "saena.policy_denied.engine_not_permitted"

    def test_rejected_registration_leaves_registry_empty(self, rogue_engine_id: str) -> None:
        registry = AdapterRegistry()
        with pytest.raises(EngineNotPermittedError):
            registry.register(FakeAdapter(rogue_engine_id))
        assert registry.enabled_engine_ids() == ()
        assert rogue_engine_id not in registry

    def test_get_also_raises_engine_not_permitted(self, rogue_engine_id: str) -> None:
        registry = AdapterRegistry()
        with pytest.raises(EngineNotPermittedError):
            registry.get(rogue_engine_id)


@pytest.mark.parametrize(
    "variant_engine_id",
    [
        "ChatGPT-Search",  # mixed case
        "CHATGPT-SEARCH",  # upper case
        "chatgpt-search ",  # trailing whitespace
        " chatgpt-search",  # leading whitespace
        "chatgpt-sеarch",  # Cyrillic 'е' (U+0435) homoglyph for Latin 'e'
    ],
    ids=[
        "mixed-case",
        "upper-case",
        "trailing-whitespace",
        "leading-whitespace",
        "cyrillic-e-homoglyph",
    ],
)
class TestRegisterRejectsNearMissVariants:
    """Locks in the no-normalization guarantee: `AdapterRegistry.register`
    does exact, byte-for-byte membership testing against
    `PERMITTED_ENGINE_IDS` -- it must never case-fold, strip, or Unicode-
    normalize a candidate `engine_id` before comparing it. A future
    refactor that adds normalization would silently widen the v1 closed
    enum (CLAUDE.md Engine scope / ADR-0013) to accept lookalike values."""

    def test_register_raises_engine_not_permitted(self, variant_engine_id: str) -> None:
        registry = AdapterRegistry()
        with pytest.raises(EngineNotPermittedError) as exc_info:
            registry.register(FakeAdapter(variant_engine_id))
        assert exc_info.value.engine_id == variant_engine_id

    def test_variant_is_not_in_permitted_engine_ids(self, variant_engine_id: str) -> None:
        assert variant_engine_id not in PERMITTED_ENGINE_IDS


class TestGetOnEmptyRegistry:
    def test_valid_engine_id_not_registered_raises_not_found(self) -> None:
        registry = AdapterRegistry()
        with pytest.raises(AdapterNotFoundError) as exc_info:
            registry.get("chatgpt-search")
        assert exc_info.value.engine_id == "chatgpt-search"
        assert exc_info.value.error_code == "saena.not_found.adapter_missing"


class TestUnsafeInsertForTesting:
    def test_bypasses_the_closed_enum_guard(self) -> None:
        registry = AdapterRegistry()
        registry._unsafe_insert_for_testing("gemini", FakeAdapter("gemini"))
        assert "gemini" in registry
        assert registry.enabled_engine_ids() == ("gemini",)

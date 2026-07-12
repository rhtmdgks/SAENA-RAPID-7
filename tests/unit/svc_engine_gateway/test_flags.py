"""`FlagRegistry`/`AdapterFlag` — per-adapter feature flags (ADR-0001)."""

from __future__ import annotations

import pytest
from saena_engine_gateway.errors import EngineNotPermittedError
from saena_engine_gateway.flags import AdapterFlag, FlagRegistry


class TestAdapterFlag:
    def test_flag_key_is_adapter_unit_scoped(self) -> None:
        flag = AdapterFlag(engine_id="chatgpt-search", enabled=True)
        assert flag.flag_key == "engine.chatgpt-search"

    def test_flag_is_immutable(self) -> None:
        flag = AdapterFlag(engine_id="chatgpt-search", enabled=True)
        with pytest.raises(AttributeError):
            flag.enabled = False  # type: ignore[misc]


class TestCreateAcceptsPermittedEngine:
    def test_create_chatgpt_search_enabled(self) -> None:
        flags = FlagRegistry()
        flag = flags.create("chatgpt-search", enabled=True)
        assert flag.engine_id == "chatgpt-search"
        assert flags.is_enabled("chatgpt-search") is True

    def test_create_chatgpt_search_disabled(self) -> None:
        flags = FlagRegistry()
        flags.create("chatgpt-search", enabled=False)
        assert flags.is_enabled("chatgpt-search") is False


@pytest.mark.parametrize(
    "rogue_engine_id",
    [
        "google-ai-overviews",
        "google-ai-mode",
        "gemini",
        "google",
        "bard",
        "chatgpt",
        "",
    ],
)
class TestCreateRejectsNonEnumEngine:
    def test_create_raises_engine_not_permitted(self, rogue_engine_id: str) -> None:
        flags = FlagRegistry()
        with pytest.raises(EngineNotPermittedError) as exc_info:
            flags.create(rogue_engine_id, enabled=True)
        assert exc_info.value.engine_id == rogue_engine_id

    def test_create_rejects_even_when_disabled(self, rogue_engine_id: str) -> None:
        """A flag for a non-enum engine cannot be created at all, on or
        off — ADR-0001 + CLAUDE.md Engine scope v1."""
        flags = FlagRegistry()
        with pytest.raises(EngineNotPermittedError):
            flags.create(rogue_engine_id, enabled=False)

    def test_is_enabled_also_raises_engine_not_permitted(self, rogue_engine_id: str) -> None:
        flags = FlagRegistry()
        with pytest.raises(EngineNotPermittedError):
            flags.is_enabled(rogue_engine_id)

    def test_get_also_raises_engine_not_permitted(self, rogue_engine_id: str) -> None:
        flags = FlagRegistry()
        with pytest.raises(EngineNotPermittedError):
            flags.get(rogue_engine_id)


class TestIsEnabledFailsClosed:
    def test_no_flag_created_resolves_to_disabled(self) -> None:
        flags = FlagRegistry()
        assert flags.is_enabled("chatgpt-search") is False

    def test_get_returns_none_when_no_flag_created(self) -> None:
        flags = FlagRegistry()
        assert flags.get("chatgpt-search") is None


class TestUnsafeInsertForTesting:
    def test_bypasses_the_closed_enum_guard(self) -> None:
        flags = FlagRegistry()
        flags._unsafe_insert_for_testing(AdapterFlag(engine_id="gemini", enabled=True))
        assert flags.flagged_engine_ids() == ("gemini",)

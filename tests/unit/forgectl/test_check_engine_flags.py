"""`saena_forgectl.checks.engine_flags` — THE named W2C exit gate.

Mirrors the engine-gateway rejection corpus
(`tests/unit/svc_engine_gateway/test_flags.py`'s `TestCreateRejectsNonEnumEngine`
parametrization) so the two "what counts as a rogue engine" surfaces —
runtime flag creation and static preflight — cannot silently diverge.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from conftest import fixture_path
from saena_forgectl.checks.engine_flags import PERMITTED_ENGINE_IDS, check_engine_flags


class TestPermittedEngineIdsIsClosedEnum:
    def test_only_chatgpt_search(self) -> None:
        assert frozenset({"chatgpt-search"}) == PERMITTED_ENGINE_IDS


class TestPassingFixture:
    def test_only_chatgpt_search_enabled_passes(self, passing_values: dict[str, Any]) -> None:
        result = check_engine_flags(passing_values)
        assert result.passed is True
        assert result.name == "engine_flags"


class TestGoogleFlagFixtureFails:
    def test_gemini_enabled_fails(self) -> None:
        import yaml

        with fixture_path("values-fail-google-flag.yaml").open(encoding="utf-8") as f:
            values = yaml.safe_load(f)
        result = check_engine_flags(values)
        assert result.passed is False
        assert "gemini" in result.detail


@pytest.mark.parametrize(
    "rogue_flag_key,engine_id",
    [
        ("googleAiOverviews", "google-ai-overviews"),
        ("googleAiMode", "google-ai-mode"),
        ("gemini", "gemini"),
        ("google", "google"),
        ("bard", "bard"),
    ],
)
class TestRogueEngineCorpusFailsWhenEnabled:
    """Every rogue engine_id -> FAIL when its flag is enabled — mirrors
    `test_flags.TestCreateRejectsNonEnumEngine`'s corpus."""

    def test_enabling_rogue_flag_fails(
        self, passing_values: dict[str, Any], rogue_flag_key: str, engine_id: str
    ) -> None:
        values = copy.deepcopy(passing_values)
        values["global"]["engineScope"][rogue_flag_key] = True
        result = check_engine_flags(values)
        assert result.passed is False
        assert engine_id in result.context["disallowed_enabled"].values()

    def test_rogue_flag_present_but_disabled_still_passes(
        self, passing_values: dict[str, Any], rogue_flag_key: str, engine_id: str
    ) -> None:
        """A known non-v1 flag key present-but-false is not itself a
        violation (mirrors §8.1's own skeleton, which lists all four keys
        with the three non-chatgpt ones `false`)."""
        values = copy.deepcopy(passing_values)
        values["global"]["engineScope"][rogue_flag_key] = False
        result = check_engine_flags(values)
        assert result.passed is True


class TestOnlyChatgptSearchPasses:
    def test_disabling_chatgpt_search_still_passes_engine_flags_check(
        self, passing_values: dict[str, Any]
    ) -> None:
        """This check only enforces the *closed enum* boundary — whether
        chatgpt-search itself is on is a separate operational concern, not
        a §8.1 condition-2 violation."""
        values = copy.deepcopy(passing_values)
        values["global"]["engineScope"]["chatgptSearch"] = False
        result = check_engine_flags(values)
        assert result.passed is True
        assert result.context["chatgptSearch_enabled"] is False


class TestUnrecognizedEngineKeyFailsClosed:
    def test_unrecognized_key_fails_even_when_true(self) -> None:
        import yaml

        with fixture_path("values-fail-unrecognized-engine-key.yaml").open(encoding="utf-8") as f:
            values = yaml.safe_load(f)
        result = check_engine_flags(values)
        assert result.passed is False
        assert "googleAiOverviewsExperimental" in result.context["unrecognized_keys"]

    def test_unrecognized_key_fails_even_when_false(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["global"]["engineScope"]["someRogueKey"] = False
        result = check_engine_flags(values)
        assert result.passed is False
        assert "someRogueKey" in result.context["unrecognized_keys"]


class TestMissingOrMalformedEngineScope:
    def test_missing_engine_scope_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        del values["global"]["engineScope"]
        result = check_engine_flags(values)
        assert result.passed is False
        assert "not declared" in result.detail

    def test_non_mapping_engine_scope_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["global"]["engineScope"] = ["not", "a", "mapping"]
        result = check_engine_flags(values)
        assert result.passed is False
        assert "must be a mapping" in result.detail

    def test_missing_global_section_fails(self) -> None:
        result = check_engine_flags({})
        assert result.passed is False

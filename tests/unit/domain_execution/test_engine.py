"""Engine guard — v1 closed engine_id enum, explicit disallowed-engine
rejection for google-aio/google-ai-mode/gemini."""

from __future__ import annotations

import pytest
from saena_domain.execution.engine import ALLOWED_ENGINE_IDS, guard_engine_id
from saena_domain.execution.errors import EngineDisallowedError, EngineNotPermittedError


def test_chatgpt_search_is_permitted() -> None:
    guard_engine_id("chatgpt-search")  # must not raise


def test_allowed_engine_ids_is_the_v1_single_value_closed_enum() -> None:
    assert frozenset({"chatgpt-search"}) == ALLOWED_ENGINE_IDS


@pytest.mark.parametrize(
    ("engine_id", "expected_name"),
    [
        ("google-aio", "Google AI Overviews"),
        ("google-ai-overviews", "Google AI Overviews"),
        ("google-ai-mode", "Google AI Mode"),
        ("gemini", "Gemini"),
    ],
)
def test_known_disallowed_engines_rejected_with_explicit_name(
    engine_id: str, expected_name: str
) -> None:
    with pytest.raises(EngineDisallowedError) as excinfo:
        guard_engine_id(engine_id)
    assert excinfo.value.engine_id == engine_id
    assert excinfo.value.disallowed_name == expected_name
    assert excinfo.value.error_code == "saena.execution.engine_disallowed"


def test_engine_disallowed_error_is_a_engine_not_permitted_error() -> None:
    """A caller that only catches the generic error still catches the
    specific one — EngineDisallowedError subclasses EngineNotPermittedError."""
    with pytest.raises(EngineNotPermittedError):
        guard_engine_id("gemini")


def test_unknown_engine_id_raises_generic_not_permitted_not_disallowed() -> None:
    with pytest.raises(EngineNotPermittedError) as excinfo:
        guard_engine_id("some-future-engine")
    assert type(excinfo.value) is EngineNotPermittedError
    assert excinfo.value.engine_id == "some-future-engine"
    assert excinfo.value.error_code == "saena.execution.engine_not_permitted"


@pytest.mark.parametrize("bad_engine_id", ["", "CHATGPT-SEARCH", "chatgpt_search", "bing"])
def test_other_non_permitted_values_rejected(bad_engine_id: str) -> None:
    with pytest.raises(EngineNotPermittedError):
        guard_engine_id(bad_engine_id)

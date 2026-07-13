"""`engine_id` guard: google/gemini rejected BEFORE any capture attempt."""

from __future__ import annotations

import pytest
from observer_discovery_factories import CHATGPT_SEARCH_ENGINE_ID, build_job_context
from saena_chatgpt_observer import (
    CapturedObservation,
    FakeObservationSource,
    run_chatgpt_observation,
)
from saena_domain.execution.errors import EngineDisallowedError, EngineNotPermittedError


@pytest.mark.parametrize(
    "engine_id",
    ["google-aio", "google-ai-overviews", "google-ai-mode", "gemini"],
)
def test_known_disallowed_engines_are_rejected(engine_id: str) -> None:
    source = FakeObservationSource()
    source.register_query(
        "q", CapturedObservation(citation_refs=(), raw_object_ref="raw://acme-co/x")
    )

    with pytest.raises(EngineDisallowedError):
        run_chatgpt_observation(
            job_context=build_job_context(),
            source=source,
            engine_id=engine_id,
            queries=["q"],
        )

    # The engine guard runs BEFORE any observation source call — this is
    # the mission's negative test in its strictest form: not merely
    # "rejected", but rejected with zero side effects on the (fake)
    # observation source.
    assert source.capture_calls == []


def test_unrecognized_engine_id_is_rejected() -> None:
    source = FakeObservationSource()

    with pytest.raises(EngineNotPermittedError):
        run_chatgpt_observation(
            job_context=build_job_context(),
            source=source,
            engine_id="bing-chat",
            queries=["q"],
        )

    assert source.capture_calls == []


def test_chatgpt_search_engine_id_is_permitted() -> None:
    source = FakeObservationSource()
    source.register_query(
        "q", CapturedObservation(citation_refs=(), raw_object_ref="raw://acme-co/x")
    )

    result = run_chatgpt_observation(
        job_context=build_job_context(),
        source=source,
        engine_id=CHATGPT_SEARCH_ENGINE_ID,
        queries=["q"],
    )

    assert result.observations[0].engine_id == CHATGPT_SEARCH_ENGINE_ID
    assert source.capture_calls == ["q"]


def test_platform_observation_construction_rejects_disallowed_engine_directly() -> None:
    """The guard is enforced at TWO layers: `run_chatgpt_observation`'s own
    call-order guard (tested above) AND `PlatformObservation.__post_init__`
    itself — even a caller that bypasses the orchestration function and
    constructs the value object directly cannot smuggle a disallowed
    `engine_id` through."""
    from saena_chatgpt_observer import PlatformObservation

    with pytest.raises(EngineDisallowedError):
        PlatformObservation(
            engine_id="gemini",
            tenant_id="acme-co",
            run_id="run-0001",
            query_text="q",
            citation_refs=(),
            raw_object_ref="raw://acme-co/x",
            observed_at="2026-07-13T00:00:00Z",
        )

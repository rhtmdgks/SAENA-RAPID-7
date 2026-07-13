"""Rate/timeout/retry enforcement for `run_chatgpt_observation`, and its
`JobKind.CHATGPT_OBSERVER`-scope guard."""

from __future__ import annotations

import pytest
from observer_discovery_factories import CHATGPT_SEARCH_ENGINE_ID, build_job_context
from saena_chatgpt_observer import (
    CapturedObservation,
    FakeObservationSource,
    JobKindScopeError,
    ObservationBudget,
    ObservationBudgetExceededError,
    ObservationDeadlineExceededError,
    ObservationRetryExhaustedError,
    observation_budget_for,
    run_chatgpt_observation,
)
from saena_domain.execution import JobKind, resource_limits_for


def test_observation_budget_for_derives_from_resource_limits_for() -> None:
    limits = resource_limits_for(JobKind.CHATGPT_OBSERVER)
    budget = observation_budget_for(JobKind.CHATGPT_OBSERVER)

    assert budget.max_retries == limits.max_retries
    assert budget.active_deadline_seconds == limits.active_deadline_seconds
    assert budget.max_queries_per_run > 0
    assert budget.request_timeout_seconds > 0


@pytest.mark.parametrize("other_kind", [JobKind.SITE_DISCOVERY, JobKind.AGENT_RUNNER])
def test_observation_budget_for_rejects_any_other_job_kind(other_kind: JobKind) -> None:
    with pytest.raises(JobKindScopeError):
        observation_budget_for(other_kind)


def test_too_many_queries_raises_budget_exceeded_before_any_capture() -> None:
    source = FakeObservationSource()
    tiny_budget = ObservationBudget(
        max_queries_per_run=1,
        request_timeout_seconds=1.0,
        max_retries=1,
        active_deadline_seconds=3600,
    )

    with pytest.raises(ObservationBudgetExceededError):
        run_chatgpt_observation(
            job_context=build_job_context(),
            source=source,
            engine_id=CHATGPT_SEARCH_ENGINE_ID,
            queries=["q1", "q2"],
            budget=tiny_budget,
        )

    assert source.capture_calls == []


def test_deadline_exceeded_mid_run_raises_and_stops() -> None:
    source = FakeObservationSource()
    source.register_query(
        "q1", CapturedObservation(citation_refs=(), raw_object_ref="raw://acme-co/1")
    )
    source.register_query(
        "q2", CapturedObservation(citation_refs=(), raw_object_ref="raw://acme-co/2")
    )
    budget = ObservationBudget(
        max_queries_per_run=10,
        request_timeout_seconds=1.0,
        max_retries=1,
        active_deadline_seconds=5,
    )
    calls = {"count": 0}

    def fake_clock() -> float:
        calls["count"] += 1
        return 0.0 if calls["count"] == 1 else 999.0

    with pytest.raises(ObservationDeadlineExceededError):
        run_chatgpt_observation(
            job_context=build_job_context(),
            source=source,
            engine_id=CHATGPT_SEARCH_ENGINE_ID,
            queries=["q1", "q2"],
            budget=budget,
            clock=fake_clock,
        )

    assert source.capture_calls == []


def test_retry_succeeds_within_max_retries() -> None:
    source = FakeObservationSource()
    source.register_query(
        "q1", CapturedObservation(citation_refs=(), raw_object_ref="raw://acme-co/1")
    )
    source.fail_next("q1", times=2)
    budget = ObservationBudget(
        max_queries_per_run=10,
        request_timeout_seconds=1.0,
        max_retries=3,
        active_deadline_seconds=3600,
    )

    result = run_chatgpt_observation(
        job_context=build_job_context(),
        source=source,
        engine_id=CHATGPT_SEARCH_ENGINE_ID,
        queries=["q1"],
        budget=budget,
    )

    assert len(result.observations) == 1
    assert source.capture_calls == ["q1", "q1", "q1"]


def test_retry_exhausted_raises() -> None:
    source = FakeObservationSource()
    source.register_query(
        "q1", CapturedObservation(citation_refs=(), raw_object_ref="raw://acme-co/1")
    )
    source.fail_next("q1", times=5)
    budget = ObservationBudget(
        max_queries_per_run=10,
        request_timeout_seconds=1.0,
        max_retries=2,
        active_deadline_seconds=3600,
    )

    with pytest.raises(ObservationRetryExhaustedError):
        run_chatgpt_observation(
            job_context=build_job_context(),
            source=source,
            engine_id=CHATGPT_SEARCH_ENGINE_ID,
            queries=["q1"],
            budget=budget,
        )

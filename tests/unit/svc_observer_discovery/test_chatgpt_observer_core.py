"""Happy-path `run_chatgpt_observation`: capture, audit, immutability."""

from __future__ import annotations

import dataclasses

import pytest
from observer_discovery_factories import CHATGPT_SEARCH_ENGINE_ID, build_job_context
from saena_chatgpt_observer import (
    CapturedObservation,
    FakeObservationSource,
    run_chatgpt_observation,
)
from saena_domain.execution import JobStatus


def _source_with_two_queries() -> FakeObservationSource:
    source = FakeObservationSource()
    source.register_query(
        "best crm for startups",
        CapturedObservation(
            citation_refs=("citation://acme-co/ref-1", "citation://acme-co/ref-2"),
            raw_object_ref="raw://acme-co/session-1",
        ),
    )
    source.register_query(
        "acme co pricing",
        CapturedObservation(citation_refs=(), raw_object_ref="raw://acme-co/session-2"),
    )
    return source


def test_run_chatgpt_observation_happy_path_produces_observations_and_audit() -> None:
    job_context = build_job_context()
    source = _source_with_two_queries()

    result = run_chatgpt_observation(
        job_context=job_context,
        source=source,
        engine_id=CHATGPT_SEARCH_ENGINE_ID,
        queries=["best crm for startups", "acme co pricing"],
    )

    assert result.final_status == JobStatus.SUCCEEDED
    assert len(result.observations) == 2
    assert all(obs.engine_id == CHATGPT_SEARCH_ENGINE_ID for obs in result.observations)
    assert all(obs.tenant_id == job_context.tenant_id for obs in result.observations)
    first = next(o for o in result.observations if o.query_text == "best crm for startups")
    assert first.citation_refs == ("citation://acme-co/ref-1", "citation://acme-co/ref-2")
    second = next(o for o in result.observations if o.query_text == "acme co pricing")
    # Zero citations is a valid, meaningful signal — never rejected.
    assert second.citation_refs == ()
    assert len(result.audit_trail) == 2
    assert all(entry.action == "captured" for entry in result.audit_trail)
    assert source.capture_calls == ["best crm for startups", "acme co pricing"]


def test_platform_observation_is_frozen_immutable() -> None:
    job_context = build_job_context()
    source = _source_with_two_queries()
    result = run_chatgpt_observation(
        job_context=job_context,
        source=source,
        engine_id=CHATGPT_SEARCH_ENGINE_ID,
        queries=["best crm for startups"],
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.observations[0].query_text = "tampered"  # type: ignore[misc]

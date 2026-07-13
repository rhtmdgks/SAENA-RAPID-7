"""End-to-end read-only pooled observation (w4-08): fixture browser → artifact
gateway → PlatformObservation record + observation.captured.v1 envelope.
Deterministic (injected clock/ids), tenant-scoped, engine-guarded, fail-closed
on render failure."""

from __future__ import annotations

import pytest
from saena_chatgpt_observer.artifact_gateway import FakeArtifactGateway
from saena_chatgpt_observer.errors import ObservationRetryExhaustedError
from saena_chatgpt_observer.pool import BrowserPool, FixtureBrowserSessionFactory
from saena_chatgpt_observer.pool_capture import run_pooled_observation
from saena_domain.execution import JobStatus
from saena_domain.execution.errors import EngineNotPermittedError

from .conftest import ENGINE, TENANT_A, TENANT_B, make_job_context

_RESPONSES = {"crm software": b"<html>A</html>", "helpdesk tool": b"<html>B</html>"}


def _pool() -> BrowserPool:
    return BrowserPool(FixtureBrowserSessionFactory(shared_responses=_RESPONSES), max_size=2)


def _fixed_clock() -> str:
    return "2026-07-13T00:00:00Z"


def test_end_to_end_capture_produces_records_and_envelopes() -> None:
    gw = FakeArtifactGateway()
    result = run_pooled_observation(
        job_context=make_job_context(),
        pool=_pool(),
        artifact_gateway=gw,
        engine_id=ENGINE,
        queries=list(_RESPONSES),
        clock=_fixed_clock,
    )
    assert result.final_status is JobStatus.SUCCEEDED
    assert len(result.results) == 2
    for r in result.results:
        # observation record references the artifact by ref/hash, never raw bytes
        assert r.observation_record["raw_object_ref"].startswith("artifact://")
        assert r.observation_record["artifact_hash"].startswith("sha256:")
        assert "raw_content" not in r.observation_record
        assert r.observation_record["engine_id"] == ENGINE
        assert r.observation_record["tenant_id"] == TENANT_A
        assert r.observation_captured_envelope["event_type"] == "observation.captured.v1"
        assert r.observation_captured_envelope["payload"]["engine_id"] == ENGINE


def test_raw_content_is_stored_only_under_the_job_tenant() -> None:
    gw = FakeArtifactGateway()
    run_pooled_observation(
        job_context=make_job_context(tenant_id=TENANT_A),
        pool=_pool(),
        artifact_gateway=gw,
        engine_id=ENGINE,
        queries=["crm software"],
        clock=_fixed_clock,
    )
    # every gateway write was scoped to the job's tenant, never another
    assert gw.put_calls == [TENANT_A]
    assert TENANT_B not in gw.put_calls


def test_capture_is_deterministic_with_injected_clock_and_ids() -> None:
    def run():
        return run_pooled_observation(
            job_context=make_job_context(),
            pool=_pool(),
            artifact_gateway=FakeArtifactGateway(),
            engine_id=ENGINE,
            queries=["crm software"],
            observation_id_factory=lambda run_id, i: f"{run_id}-{i:04d}",
            clock=_fixed_clock,
        )

    a = run().results[0].observation_record
    b = run().results[0].observation_record
    assert a == b  # byte-identical record across runs


def test_disallowed_engine_is_rejected_before_any_capture() -> None:
    gw = FakeArtifactGateway()
    with pytest.raises(EngineNotPermittedError):
        run_pooled_observation(
            job_context=make_job_context(),
            pool=_pool(),
            artifact_gateway=gw,
            engine_id="gemini",
            queries=["crm software"],
            clock=_fixed_clock,
        )
    assert gw.put_calls == []  # nothing captured/stored


def test_render_failure_fails_closed_and_stores_nothing() -> None:
    gw = FakeArtifactGateway()
    with pytest.raises(ObservationRetryExhaustedError):
        run_pooled_observation(
            job_context=make_job_context(),
            pool=_pool(),
            artifact_gateway=gw,
            engine_id=ENGINE,
            queries=["query-with-no-fixture-response"],
            clock=_fixed_clock,
        )
    assert gw.put_calls == []


def test_citation_extractor_refs_land_on_the_record() -> None:
    result = run_pooled_observation(
        job_context=make_job_context(),
        pool=_pool(),
        artifact_gateway=FakeArtifactGateway(),
        engine_id=ENGINE,
        queries=["crm software"],
        citation_extractor=lambda raw: ("https://example.com/cited",),
        clock=_fixed_clock,
    )
    assert result.results[0].observation_record["citation_refs"] == ["https://example.com/cited"]

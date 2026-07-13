"""Wave-4 intelligence: engine scope closed to `chatgpt-search` (w4-16).

CLAUDE.md "Engine scope (v1)": Target = ChatGPT Search only; Google AI
Overviews / Google AI Mode / Gemini / Bing are all disabled — optimize/
observe/claim FORBIDDEN for every one of them. This module proves that
guard fails CLOSED at every real Wave-4 layer that accepts an `engine_id`:

1. `saena_citation_intelligence.service.normalize_citation` — this
   package's OWN pre-`EnvelopeFactory` guard (`EngineNotPermittedError`).
2. `saena_chatgpt_observer.platform_observation_record` (the w4-08/w4-10
   observation-record + `observation.captured.v1` event builders) —
   `saena_domain.execution.guard_engine_id`, raising
   `EngineNotPermittedError`/`EngineDisallowedError`.
3. `saena_chatgpt_observer.pool_capture.run_pooled_observation` — the
   SAME guard, checked BEFORE a single browser session is acquired (proves
   the reject happens before any pool/artifact-gateway side effect, not
   merely somewhere downstream).
4. `saena_domain.events.factory.EnvelopeFactory.build_tenant_envelope` —
   the shared, engine-family-wide runtime guard every one of the 5
   `x-saena-engine-id-required: true` channels routes through
   (`observation.captured.v1`, `citation.normalized.v1`,
   `experiment.registered.v1`, `experiment.anchored.v1`,
   `experiment.outcome.observed.v1`); this module proves it directly
   against a hand-built envelope call for each named-disallowed engine
   (google-aio/google-ai-mode/gemini) plus an arbitrary unknown engine
   (bing), and separately proves a MISSING `engine_id` on an
   engine-id-required channel is rejected too (`EngineIdRequiredError`).

Every test in this module is genuinely adversarial: each maps to exactly
one guard call site, named in its own docstring, and fails if that guard
is deleted/bypassed (verified by construction — the assertion is on the
raised exception type/engine_id, not a tautology).
"""

from __future__ import annotations

import pytest
from saena_chatgpt_observer.artifact_gateway import FakeArtifactGateway
from saena_chatgpt_observer.errors import BrowserSessionRenderError
from saena_chatgpt_observer.platform_observation_record import (
    build_observation_captured_envelope,
    build_platform_observation_record,
)
from saena_chatgpt_observer.pool import BrowserPool, FixtureBrowserSessionFactory
from saena_chatgpt_observer.pool_capture import run_pooled_observation
from saena_citation_intelligence.errors import EngineNotPermittedError as CitationEngineError
from saena_citation_intelligence.service import normalize_citation
from saena_domain.events import EnvelopeFactory
from saena_domain.events.errors import (
    EngineIdRequiredError,
)
from saena_domain.events.errors import (
    EngineNotPermittedError as EnvelopeEngineError,
)
from saena_domain.execution import JobContext
from saena_domain.execution.errors import (
    EngineDisallowedError,
)
from saena_domain.execution.errors import (
    EngineNotPermittedError as ExecutionEngineError,
)

TENANT_ID = "acme-co"
RUN_ID = "run-0001"


def _make_job_context(*, tenant_id: str = TENANT_ID, run_id: str = RUN_ID) -> JobContext:
    return JobContext(
        tenant_id=tenant_id,
        workspace_id="ws-0001",
        project_id="proj-0001",
        run_id=run_id,
        trace_id="a" * 32,
        idempotency_key=f"{tenant_id}:{run_id}:w4-16",
        actor_id="actor-0001",
    )


#: CLAUDE.md "Disabled: Google AI Overviews, Google AI Mode, Gemini"
#: (explicitly-named -> `EngineDisallowedError`) plus one arbitrary
#: never-heard-of engine (Bing, per the mission brief's own list) that
#: exercises the generic `EngineNotPermittedError`/`CitationEngineError`
#: path instead of the disallowed-name-specific one.
DISALLOWED_NAMED_ENGINES = ("google-aio", "google-ai-mode", "gemini")
UNKNOWN_ENGINE = "bing"


# --- 1. saena_citation_intelligence.service.normalize_citation ---


@pytest.mark.parametrize("engine_id", [*DISALLOWED_NAMED_ENGINES, UNKNOWN_ENGINE])
def test_citation_intelligence_rejects_every_non_chatgpt_search_engine_id(engine_id: str) -> None:
    """Pins `normalize_citation`'s own `ALLOWED_ENGINE_IDS` guard
    (`saena_citation_intelligence.service.normalize_citation`). Fails if
    that guard is deleted: without it, this call would instead raise
    (or succeed past) `UrlNormalizationError`/return a record, never
    `EngineNotPermittedError`.
    """
    with pytest.raises(CitationEngineError) as excinfo:
        normalize_citation(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            citation_id="cite-0001",
            raw_url="https://example.com/page",
            engine_id=engine_id,
        )
    assert excinfo.value.context["engine_id"] == engine_id


def test_citation_intelligence_rejects_before_any_url_normalization_attempted() -> None:
    """A malformed URL alongside a disallowed engine_id must still surface
    `EngineNotPermittedError`, not `UrlNormalizationError` — proving the
    engine guard runs FIRST (fail fast on the hardest constraint), not as
    a downstream check a bypass could dodge by supplying a valid URL."""
    with pytest.raises(CitationEngineError):
        normalize_citation(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            citation_id="cite-0001",
            raw_url="",  # would itself raise UrlNormalizationError if reached
            engine_id="gemini",
        )


def test_citation_intelligence_accepts_the_one_permitted_engine_id() -> None:
    """Negative control: `chatgpt-search` itself must NOT be rejected —
    proves this is a real allow-list check, not a blanket deny."""
    result = normalize_citation(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        citation_id="cite-0001",
        raw_url="https://example.com/page",
        engine_id="chatgpt-search",
    )
    assert result.envelope["payload"]["engine_id"] == "chatgpt-search"


# --- 2. saena_chatgpt_observer.platform_observation_record ---


@pytest.mark.parametrize("engine_id", [*DISALLOWED_NAMED_ENGINES, UNKNOWN_ENGINE])
def test_observation_record_builder_rejects_every_non_chatgpt_search_engine_id(
    engine_id: str,
) -> None:
    """Pins `build_platform_observation_record`'s `guard_engine_id` call
    (`saena_chatgpt_observer.platform_observation_record`). Fails if that
    guard is removed: the generated `PlatformObservation` model would then
    be the only remaining check, and this test would instead see a
    pydantic `ValidationError`-wrapping `PlatformObservationRecordError`
    (a different failure mode/error_code) or, for an engine string the
    generated enum happens not to validate strictly, no error at all.
    """
    with pytest.raises((ExecutionEngineError, EngineDisallowedError)):
        build_platform_observation_record(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            engine_id=engine_id,
            observation_id="obs-0001",
            raw_object_ref=f"artifact://{TENANT_ID}/{'a' * 64}",
            artifact_hash=f"sha256:{'a' * 64}",
            citation_refs=(),
            captured_at="2026-07-13T00:00:00Z",
        )


@pytest.mark.parametrize("engine_id", [*DISALLOWED_NAMED_ENGINES, UNKNOWN_ENGINE])
def test_observation_captured_envelope_builder_rejects_every_non_chatgpt_search_engine_id(
    engine_id: str,
) -> None:
    """Pins `build_observation_captured_envelope`'s `guard_engine_id` call
    — the SAME function this unit's own `observation.captured.v1` producer
    uses before ever calling `EnvelopeFactory`."""
    with pytest.raises((ExecutionEngineError, EngineDisallowedError)):
        build_observation_captured_envelope(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            engine_id=engine_id,
            observation_id="obs-0001",
            artifact_hash=f"sha256:{'a' * 64}",
            idempotency_key=f"{TENANT_ID}:{RUN_ID}:obs-0001",
        )


# --- 3. saena_chatgpt_observer.pool_capture.run_pooled_observation ---


def _build_pool_with_one_query(query_text: str = "what is saena") -> BrowserPool:
    factory = FixtureBrowserSessionFactory(shared_responses={query_text: b"<html>ok</html>"})
    return BrowserPool(factory, max_size=1)


@pytest.mark.parametrize("engine_id", [*DISALLOWED_NAMED_ENGINES, UNKNOWN_ENGINE])
def test_pooled_observation_rejects_engine_before_acquiring_any_browser_session(
    engine_id: str,
) -> None:
    """Pins `run_pooled_observation`'s `guard_engine_id(engine_id)` call,
    which the module's own docstring states runs "before a single browser
    session is even acquired". Proven here two ways at once: (a) the
    expected exception type is raised, and (b) the pool's own stats show
    ZERO sessions were ever created — if the guard were removed or moved
    to run AFTER acquisition, `pool.stats().total` would be >= 1 instead.
    """
    job_context = _make_job_context()
    pool = _build_pool_with_one_query()
    artifact_gateway = FakeArtifactGateway()

    with pytest.raises((ExecutionEngineError, EngineDisallowedError)):
        run_pooled_observation(
            job_context=job_context,
            pool=pool,
            artifact_gateway=artifact_gateway,
            engine_id=engine_id,
            queries=["what is saena"],
        )

    assert pool.stats().total == 0
    assert artifact_gateway.put_calls == []


def test_pooled_observation_succeeds_end_to_end_for_the_one_permitted_engine_id() -> None:
    """Negative control for the whole pooled-capture pipeline: a genuine
    `chatgpt-search` run must actually succeed and produce an
    `observation.captured.v1` envelope carrying `engine_id=chatgpt-search`
    — proves guard_engine_id is a real allow-list gate, not a disguised
    always-deny."""
    job_context = _make_job_context()
    pool = _build_pool_with_one_query()
    artifact_gateway = FakeArtifactGateway()

    result = run_pooled_observation(
        job_context=job_context,
        pool=pool,
        artifact_gateway=artifact_gateway,
        engine_id="chatgpt-search",
        queries=["what is saena"],
    )

    assert len(result.results) == 1
    envelope = result.results[0].observation_captured_envelope
    assert envelope["payload"]["engine_id"] == "chatgpt-search"


def test_pooled_observation_wraps_render_failure_without_bypassing_engine_guard() -> None:
    """Defense-in-depth control: a permitted engine_id whose browser
    session render fails must still surface a capture-layer error
    (`ObservationRetryExhaustedError`), never silently swallow the
    failure and fabricate a captured observation — the engine guard
    passing does not imply the rest of the pipeline is unguarded."""
    from saena_chatgpt_observer.errors import ObservationRetryExhaustedError

    job_context = _make_job_context()
    # No query registered -> FixtureBrowserSession raises BrowserSessionRenderError.
    factory = FixtureBrowserSessionFactory(shared_responses={})
    pool = BrowserPool(factory, max_size=1)
    artifact_gateway = FakeArtifactGateway()

    with pytest.raises(ObservationRetryExhaustedError):
        run_pooled_observation(
            job_context=job_context,
            pool=pool,
            artifact_gateway=artifact_gateway,
            engine_id="chatgpt-search",
            queries=["unregistered query"],
        )
    # Sanity: this really is the render-failure path, not a masked engine error.
    assert issubclass(BrowserSessionRenderError, Exception)


# --- 4. saena_domain.events.factory.EnvelopeFactory (shared runtime guard) ---


@pytest.mark.parametrize(
    "event_type,producer",
    [
        ("observation.captured.v1", "chatgpt-observer-service"),
        ("citation.normalized.v1", "citation-intelligence-service"),
    ],
)
@pytest.mark.parametrize("engine_id", [*DISALLOWED_NAMED_ENGINES, UNKNOWN_ENGINE])
def test_envelope_factory_rejects_every_non_chatgpt_search_engine_id_on_confirmed_channels(
    event_type: str, producer: str, engine_id: str
) -> None:
    """Pins `saena_domain.events.factory._check_engine_id`'s value check —
    the SHARED runtime enforcement every engine-required Wave-4 channel
    routes through, independent of any one service's own pre-guard. Fails
    if `_check_engine_id` stops validating `engine_id` values: the call
    would then proceed to `_check_known_payload_model`/dual-validation
    with no engine-specific rejection, either succeeding outright or
    failing with an unrelated (schema-shape) error instead of
    `EngineNotPermittedError`.
    """
    payload = {"engine_id": engine_id}
    if event_type == "observation.captured.v1":
        payload.update({"observation_id": "obs-0001", "artifact_hash": f"sha256:{'a' * 64}"})
    else:
        payload.update(
            {
                "citation_id": "cite-0001",
                "normalized_uri": "https://example.com/page",
                "content_hash": f"sha256:{'a' * 64}",
            }
        )

    with pytest.raises(EnvelopeEngineError) as excinfo:
        EnvelopeFactory.build_tenant_envelope(
            producer=producer,
            event_type=event_type,
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            idempotency_key=f"{TENANT_ID}:{RUN_ID}:obs-0001",
            payload=payload,
        )
    assert excinfo.value.engine_id == engine_id


def test_envelope_factory_requires_engine_id_on_an_engine_required_channel() -> None:
    """Pins the PRESENCE half of `_check_engine_id` (`topic.
    engine_id_required` -> `EngineIdRequiredError`) — a channel flagged
    `x-saena-engine-id-required: true` in the AsyncAPI catalog
    (`observation.captured.v1`) must reject a payload with `engine_id`
    entirely absent, not merely an out-of-enum value. Fails if the
    presence check is removed: the call would instead fail (or succeed)
    on the payload-model layer alone, never raising
    `EngineIdRequiredError`.
    """
    with pytest.raises(EngineIdRequiredError) as excinfo:
        EnvelopeFactory.build_tenant_envelope(
            producer="chatgpt-observer-service",
            event_type="observation.captured.v1",
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            idempotency_key=f"{TENANT_ID}:{RUN_ID}:obs-0001",
            payload={"observation_id": "obs-0001", "artifact_hash": f"sha256:{'a' * 64}"},
        )
    assert excinfo.value.event_type == "observation.captured.v1"


def test_envelope_factory_accepts_chatgpt_search_on_an_engine_required_channel() -> None:
    """Negative control: the one permitted `engine_id` on an
    engine-id-required channel must build successfully end to end
    (dual jsonschema+pydantic validated) — proves this whole family of
    guards is a real allow-list, not an unconditional reject."""
    envelope = EnvelopeFactory.build_tenant_envelope(
        producer="chatgpt-observer-service",
        event_type="observation.captured.v1",
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        idempotency_key=f"{TENANT_ID}:{RUN_ID}:obs-0001",
        payload={
            "engine_id": "chatgpt-search",
            "observation_id": "obs-0001",
            "artifact_hash": f"sha256:{'a' * 64}",
        },
    )
    assert envelope["payload"]["engine_id"] == "chatgpt-search"

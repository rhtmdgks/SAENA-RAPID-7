"""Construction-time validation for `ContentRecordProjection` and
`PlatformObservation` — the "never carries raw content, evidence is always
an opaque reference" invariant both share."""

from __future__ import annotations

import pytest
from observer_discovery_factories import CHATGPT_SEARCH_ENGINE_ID
from saena_chatgpt_observer import ObservationValidationError, PlatformObservation
from saena_site_discovery import RecordValidationError, RenderMode
from saena_site_discovery.records import ContentRecordProjection


def test_fetched_record_requires_non_empty_evidence_ref() -> None:
    with pytest.raises(RecordValidationError):
        ContentRecordProjection(
            route_path="/",
            render_mode=RenderMode.STATIC,
            robots_allowed=True,
            canonical_url=None,
            sitemap_listed=False,
            structured_data_present=False,
            evidence_ref="",
            observed_at="2026-07-13T00:00:00Z",
        )


def test_disallowed_record_must_not_carry_an_evidence_ref() -> None:
    with pytest.raises(RecordValidationError):
        ContentRecordProjection(
            route_path="/admin",
            render_mode=RenderMode.UNKNOWN,
            robots_allowed=False,
            canonical_url=None,
            sitemap_listed=False,
            structured_data_present=False,
            evidence_ref="evidence://acme-co/should-not-exist",
            observed_at="2026-07-13T00:00:00Z",
        )


def test_evidence_ref_must_be_opaque_scheme_shaped() -> None:
    with pytest.raises(RecordValidationError):
        ContentRecordProjection(
            route_path="/",
            render_mode=RenderMode.STATIC,
            robots_allowed=True,
            canonical_url=None,
            sitemap_listed=False,
            structured_data_present=False,
            evidence_ref="https://example.com/page?token=secret",
            observed_at="2026-07-13T00:00:00Z",
        )


def test_platform_observation_requires_non_empty_raw_object_ref() -> None:
    with pytest.raises(ObservationValidationError):
        PlatformObservation(
            engine_id=CHATGPT_SEARCH_ENGINE_ID,
            tenant_id="acme-co",
            run_id="run-0001",
            query_text="q",
            citation_refs=(),
            raw_object_ref="",
            observed_at="2026-07-13T00:00:00Z",
        )


def test_platform_observation_citation_ref_must_be_opaque_scheme_shaped() -> None:
    with pytest.raises(ObservationValidationError):
        PlatformObservation(
            engine_id=CHATGPT_SEARCH_ENGINE_ID,
            tenant_id="acme-co",
            run_id="run-0001",
            query_text="q",
            citation_refs=("https://example.com/cited?session=secret",),
            raw_object_ref="raw://acme-co/x",
            observed_at="2026-07-13T00:00:00Z",
        )


def test_platform_observation_allows_zero_citations() -> None:
    observation = PlatformObservation(
        engine_id=CHATGPT_SEARCH_ENGINE_ID,
        tenant_id="acme-co",
        run_id="run-0001",
        query_text="q",
        citation_refs=(),
        raw_object_ref="raw://acme-co/x",
        observed_at="2026-07-13T00:00:00Z",
    )
    assert observation.citation_refs == ()

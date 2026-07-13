"""w4-13: real-container composite integration test — observation ->
artifact -> ClickHouse -> citation.normalized.v1, chaining ONLY
already-built Wave-4 components (no reimplementation):

    saena_chatgpt_observer.pool_capture.run_pooled_observation
        -> saena_chatgpt_observer.artifact_gateway.FakeArtifactGateway
        -> saena_analytics_clickhouse.store.ClickHouseAnalyticsStore (REAL ClickHouse)
        -> saena_citation_intelligence.service.normalize_citation

Docker unavailable / `clickhouse-connect` not installed -> every test in
this module is skipped with an honest, distinct reason (`conftest.py::
pytest_collection_modifyitems`), never silently passed.

Assertions match the mission's own acceptance list:

    1. `run_pooled_observation` produces a `PlatformObservation` record +
       `observation.captured.v1` envelope, `engine_id="chatgpt-search"`.
    2. Raw content never leaves the artifact gateway — the observation
       record/row/ClickHouse table carry only `raw_object_ref`/
       `artifact_hash`, never raw HTML bytes.
    3. Observation metadata persists to ClickHouse append-only,
       tenant-scoped (`get_observations(tenant_id)` never cross-tenant).
    4. `citation.normalized.v1` is produced from the observation's citation
       refs; `normalized_uri` is deterministic (byte-identical across two
       independent runs of the same input).
    5. End-to-end tenant isolation holds across the WHOLE chain (a
       cross-tenant ClickHouse query returns nothing for either table);
       `engine_id` stays `chatgpt-search` throughout; `final_status` is
       `JobStatus.SUCCEEDED` for a clean run.
"""

from __future__ import annotations

import pytest
from pipeline_helpers import (
    ENGINE_ID,
    ChainRunResult,
    citation_extractor_for,
    make_job_context,
    run_capture_store_and_normalize_chain,
)
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore
from saena_domain.execution import JobStatus

pytestmark = pytest.mark.integration

TENANT_A = "acme-co"
TENANT_B = "globex-co"

_QUERY_A = "best crm for startups"
_RESPONSE_A = b"<html><body>chatgpt search result A</body></html>"
_CITATIONS_A = ("https://example.com/crm-guide?utm_source=chatgpt#top", "https://Reddit.com/r/crm/")

_QUERY_B = "helpdesk tool comparison"
_RESPONSE_B = b"<html><body>chatgpt search result B</body></html>"
_CITATIONS_B = ("https://competitor.example/helpdesk",)


def _single_query_run(
    *,
    tenant_id: str,
    run_id: str,
    analytics_store: ClickHouseAnalyticsStore,
    tenant_owned_domains: frozenset[str] = frozenset(),
    competitor_domains: frozenset[str] = frozenset(),
) -> ChainRunResult:
    return run_capture_store_and_normalize_chain(
        job_context=make_job_context(tenant_id=tenant_id, run_id=run_id),
        queries=[_QUERY_A],
        responses={_QUERY_A: _RESPONSE_A},
        citation_urls_by_response={_RESPONSE_A: _CITATIONS_A},
        analytics_store=analytics_store,
        tenant_owned_domains=tenant_owned_domains,
        competitor_domains=competitor_domains,
    )


class TestObservationCapture:
    def test_capture_produces_platform_observation_and_envelope(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        run_result = _single_query_run(
            tenant_id=TENANT_A, run_id="run-capture-1", analytics_store=analytics_store
        )
        assert run_result.final_status is JobStatus.SUCCEEDED
        (chain_result,) = run_result.results
        record = chain_result.pooled.observation_record
        envelope = chain_result.pooled.observation_captured_envelope

        assert record["engine_id"] == ENGINE_ID
        assert record["tenant_id"] == TENANT_A
        assert envelope["event_type"] == "observation.captured.v1"
        assert envelope["payload"]["engine_id"] == ENGINE_ID
        assert envelope["payload"]["observation_id"] == record["observation_id"]

    def test_raw_content_never_leaves_the_artifact_gateway(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        (chain_result,) = _single_query_run(
            tenant_id=TENANT_A, run_id="run-capture-2", analytics_store=analytics_store
        ).results
        record = chain_result.pooled.observation_record

        # only ref/hash fields survive into the record — never raw bytes.
        assert record["raw_object_ref"].startswith("artifact://")
        assert record["artifact_hash"].startswith("sha256:")
        assert "raw_content" not in record
        assert _RESPONSE_A not in repr(record).encode("utf-8")

        # the observation row stored in ClickHouse mirrors the same discipline.
        row = chain_result.observation_row
        assert row.raw_object_ref == record["raw_object_ref"]
        # r4-04: the row carries only an opaque `query_ref`, never the raw
        # query text at all — the raw response bytes cannot appear in it by
        # construction (there is no field capable of holding them).
        assert _RESPONSE_A.decode() not in row.query_ref
        assert _RESPONSE_A not in repr(row).encode("utf-8")


class TestClickHouseAppendOnlyTenantScoped:
    def test_observation_row_round_trips_from_a_real_clickhouse_container(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        (chain_result,) = _single_query_run(
            tenant_id=TENANT_A, run_id="run-store-1", analytics_store=analytics_store
        ).results
        (fetched,) = analytics_store.get_observations(TENANT_A)
        assert fetched.id == chain_result.observation_row.id
        assert fetched.raw_object_ref == chain_result.observation_row.raw_object_ref
        assert fetched.citation_refs == chain_result.observation_row.citation_refs
        assert fetched.engine_id == ENGINE_ID

    def test_citation_rows_round_trip_from_a_real_clickhouse_container(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        (chain_result,) = _single_query_run(
            tenant_id=TENANT_A, run_id="run-store-2", analytics_store=analytics_store
        ).results
        stored_citations = analytics_store.get_citations(TENANT_A)
        assert len(stored_citations) == len(_CITATIONS_A)
        stored_ids = {row.id for row in stored_citations}
        expected_ids = {row.id for row in chain_result.citation_rows}
        assert stored_ids == expected_ids

    def test_repeated_chain_run_with_same_ids_is_append_only_idempotent(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        # Running the SAME deterministic chain twice (same tenant/run/query
        # -> same observation_id/idempotency_key) must not duplicate rows —
        # `ClickHouseAnalyticsStore.append_*`'s own idempotency-key dedup
        # (existence check before INSERT), exercised here through the full
        # composite chain rather than directly against the store.
        _single_query_run(
            tenant_id=TENANT_A, run_id="run-store-dup", analytics_store=analytics_store
        )
        _single_query_run(
            tenant_id=TENANT_A, run_id="run-store-dup", analytics_store=analytics_store
        )
        assert len(analytics_store.get_observations(TENANT_A)) == 1
        assert len(analytics_store.get_citations(TENANT_A)) == len(_CITATIONS_A)

    def test_no_raw_customer_content_lands_in_clickhouse_only_hashes_refs_metadata(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        _single_query_run(tenant_id=TENANT_A, run_id="run-store-3", analytics_store=analytics_store)
        (obs_row,) = analytics_store.get_observations(TENANT_A)
        citation_rows = analytics_store.get_citations(TENANT_A)

        # the observation row's own fields are all ref/hash/metadata shaped
        assert obs_row.raw_object_ref.startswith("artifact://")
        assert _RESPONSE_A not in repr(obs_row).encode("utf-8")
        # r4-04: `query_ref` is a short opaque reference, never a raw query
        # string (let alone a raw page) — it is a `query://` URI, not text.
        assert obs_row.query_ref.startswith("query://")
        assert len(obs_row.query_ref) < 200
        assert _QUERY_A not in obs_row.query_ref

        # citation rows carry only normalized/hashed refs, never raw HTML
        for row in citation_rows:
            assert row.citation_ref.startswith("citation://")
            assert _RESPONSE_A not in repr(row).encode("utf-8")


class TestCitationNormalization:
    def test_citation_normalized_v1_produced_from_observation_citation_refs(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        (chain_result,) = _single_query_run(
            tenant_id=TENANT_A, run_id="run-citation-1", analytics_store=analytics_store
        ).results
        assert len(chain_result.citation_normalizations) == len(_CITATIONS_A)
        for normalization in chain_result.citation_normalizations:
            assert normalization.envelope["event_type"] == "citation.normalized.v1"
            assert normalization.envelope["payload"]["engine_id"] == ENGINE_ID
            assert normalization.record.tenant_id == TENANT_A

    def test_normalized_uri_strips_query_and_fragment_deterministically(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        (chain_result,) = _single_query_run(
            tenant_id=TENANT_A, run_id="run-citation-2", analytics_store=analytics_store
        ).results
        normalized_uris = {n.record.normalized_uri for n in chain_result.citation_normalizations}
        assert "https://example.com/crm-guide" in normalized_uris
        assert "https://reddit.com/r/crm" in normalized_uris
        for uri in normalized_uris:
            assert "?" not in uri
            assert "#" not in uri

    def test_normalized_uri_is_byte_identical_across_two_independent_runs(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        (first,) = _single_query_run(
            tenant_id=TENANT_A, run_id="run-citation-det-1", analytics_store=analytics_store
        ).results
        (second,) = _single_query_run(
            tenant_id=TENANT_A, run_id="run-citation-det-2", analytics_store=analytics_store
        ).results
        first_uris = sorted(n.record.normalized_uri for n in first.citation_normalizations)
        second_uris = sorted(n.record.normalized_uri for n in second.citation_normalizations)
        assert first_uris == second_uris

    def test_engine_id_stays_chatgpt_search_across_the_whole_chain(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        (chain_result,) = _single_query_run(
            tenant_id=TENANT_A, run_id="run-citation-3", analytics_store=analytics_store
        ).results
        assert chain_result.pooled.observation_record["engine_id"] == ENGINE_ID
        assert chain_result.pooled.observation_captured_envelope["payload"]["engine_id"] == (
            ENGINE_ID
        )
        assert chain_result.observation_row.engine_id == ENGINE_ID
        for normalization in chain_result.citation_normalizations:
            assert normalization.envelope["payload"]["engine_id"] == ENGINE_ID


class TestEndToEndTenantIsolation:
    def test_cross_tenant_observation_query_returns_nothing(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        _single_query_run(tenant_id=TENANT_A, run_id="run-iso-1", analytics_store=analytics_store)
        run_capture_store_and_normalize_chain(
            job_context=make_job_context(tenant_id=TENANT_B, run_id="run-iso-1b"),
            queries=[_QUERY_B],
            responses={_QUERY_B: _RESPONSE_B},
            citation_urls_by_response={_RESPONSE_B: _CITATIONS_B},
            analytics_store=analytics_store,
        )

        tenant_a_ids = {row.tenant_id for row in analytics_store.get_observations(TENANT_A)}
        tenant_b_ids = {row.tenant_id for row in analytics_store.get_observations(TENANT_B)}
        assert tenant_a_ids == {TENANT_A}
        assert tenant_b_ids == {TENANT_B}
        # cross-tenant leakage check: tenant A's query never returns tenant B rows.
        assert TENANT_B not in tenant_a_ids
        assert TENANT_A not in tenant_b_ids

    def test_cross_tenant_citation_query_returns_nothing(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        _single_query_run(tenant_id=TENANT_A, run_id="run-iso-2", analytics_store=analytics_store)
        run_capture_store_and_normalize_chain(
            job_context=make_job_context(tenant_id=TENANT_B, run_id="run-iso-2b"),
            queries=[_QUERY_B],
            responses={_QUERY_B: _RESPONSE_B},
            citation_urls_by_response={_RESPONSE_B: _CITATIONS_B},
            analytics_store=analytics_store,
        )

        tenant_a_citations = analytics_store.get_citations(TENANT_A)
        tenant_b_citations = analytics_store.get_citations(TENANT_B)
        assert len(tenant_a_citations) == len(_CITATIONS_A)
        assert len(tenant_b_citations) == len(_CITATIONS_B)
        assert {row.tenant_id for row in tenant_a_citations} == {TENANT_A}
        assert {row.tenant_id for row in tenant_b_citations} == {TENANT_B}

    def test_raw_content_is_scoped_to_the_owning_tenant_through_the_artifact_gateway(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        # Two DIFFERENT tenants observing the SAME query text/response bytes
        # must never leak a cross-tenant `raw_object_ref` into either
        # tenant's ClickHouse row — the artifact gateway's own tenant-scoped
        # storage (`FakeArtifactGateway.put_raw_artifact`) is what this
        # asserts end to end.
        run_capture_store_and_normalize_chain(
            job_context=make_job_context(tenant_id=TENANT_A, run_id="run-iso-3a"),
            queries=[_QUERY_A],
            responses={_QUERY_A: _RESPONSE_A},
            citation_urls_by_response={_RESPONSE_A: _CITATIONS_A},
            analytics_store=analytics_store,
        )
        run_capture_store_and_normalize_chain(
            job_context=make_job_context(tenant_id=TENANT_B, run_id="run-iso-3b"),
            queries=[_QUERY_A],
            responses={_QUERY_A: _RESPONSE_A},
            citation_urls_by_response={_RESPONSE_A: _CITATIONS_A},
            analytics_store=analytics_store,
        )

        (row_a,) = analytics_store.get_observations(TENANT_A)
        (row_b,) = analytics_store.get_observations(TENANT_B)
        assert row_a.raw_object_ref.startswith(f"artifact://{TENANT_A}/")
        assert row_b.raw_object_ref.startswith(f"artifact://{TENANT_B}/")
        assert row_a.raw_object_ref != row_b.raw_object_ref

    def test_final_status_is_succeeded_for_a_clean_multi_query_chain_run(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        run_result = run_capture_store_and_normalize_chain(
            job_context=make_job_context(tenant_id=TENANT_A, run_id="run-status-1"),
            queries=[_QUERY_A, _QUERY_B],
            responses={_QUERY_A: _RESPONSE_A, _QUERY_B: _RESPONSE_B},
            citation_urls_by_response={_RESPONSE_A: _CITATIONS_A, _RESPONSE_B: _CITATIONS_B},
            analytics_store=analytics_store,
        )
        assert run_result.final_status is JobStatus.SUCCEEDED
        assert len(run_result.results) == 2
        for chain_result in run_result.results:
            assert chain_result.pooled.observation_record["engine_id"] == ENGINE_ID


def test_citation_extractor_helper_maps_exact_response_bytes_to_opaque_uri_ref_shaped_refs() -> (
    None
):
    """Unit-shaped sanity check on the composite-suite's own deterministic
    citation extractor helper (not a container-dependent test — collected
    regardless of Docker availability since it imports nothing from
    `saena_analytics_clickhouse`/`saena_citation_intelligence`). The
    extractor's own output must be `uri_ref`-shaped (`PlatformObservation.
    citation_refs`' own contract requirement — see `pipeline_helpers.py`'s
    "Field-shape note"), never a raw citation URL verbatim (which may carry
    a forbidden query string/fragment, as `_CITATIONS_A[0]` deliberately
    does)."""
    extractor = citation_extractor_for(TENANT_A, {_RESPONSE_A: _CITATIONS_A})
    refs = extractor(_RESPONSE_A)
    assert len(refs) == len(_CITATIONS_A)
    for ref in refs:
        assert ref.startswith(f"citation://{TENANT_A}/")
        assert "?" not in ref
        assert "#" not in ref
    assert extractor(b"<html>unregistered</html>") == ()

"""Shared, deterministic helpers for the w4-13 composite pipeline suite.

Uniquely-named module (not `conftest`) so sibling test modules can
`from pipeline_helpers import ...` — the same "uniquely-named-module"
convention `tests/unit/domain_persistence/persistence_factories.py`'s own
docstring documents and requires (a bare `conftest` import collides across
directories under pytest's default `prepend` import mode); this conftest's
own `sys.path` insert of `_THIS_DIR` is what makes the plain top-level
import below resolve.

This module never reimplements any already-built Wave-4 component — it
only chains them:

    1. `run_pooled_observation` (fixture browser pool + `FakeArtifactGateway`)
       -> `PlatformObservation` record + `observation.captured.v1` envelope.
    2. The observation's `citation_refs` are turned into `ObservationRow`/
       `CitationRow` `saena_analytics_clickhouse` rows and appended to a
       REAL ClickHouse container via `ClickHouseAnalyticsStore`.
    3. Each raw (pre-normalization) citation URL is passed through
       `saena_citation_intelligence.service.normalize_citation` to produce a
       `citation.normalized.v1` envelope + immutable `CitationRecord`.

Field-shape note (discovered by this suite against the REAL generated
`PlatformObservation` contract model, `saena_schemas.domain.
platform_observation_v1`): that model's `citation_refs` field is itself
`uri_ref`-typed (query strings/fragments structurally FORBIDDEN,
`^[a-z0-9+.-]+://[^?#]+$` — the same contract shape `saena_citation_
intelligence.normalization.normalize_url` produces as OUTPUT, never as
input). A caller's `CitationExtractor` therefore cannot emit an arbitrary
raw citation URL (which may legitimately carry a tracking query string,
e.g. `?utm_source=chatgpt`) directly into `citation_refs` — this module's
own `citation_extractor_for` emits an OPAQUE, already-`uri_ref`-shaped
`citation://<tenant>/<sha256(raw_url)>` ref per raw URL instead (mirroring
`RawArtifactGatewayPort`'s own opaque-ref discipline), and
`run_capture_store_and_normalize_chain` carries the raw (pre-normalization)
URLs alongside, POSITION-ALIGNED with the observation's `citation_refs`, so
step 3 can still normalize the ORIGINAL raw URL (exercising `normalize_url`'s
own query/fragment-stripping) while step 1's `PlatformObservation` record
only ever carries the contract-valid opaque ref.

Every raw HTML response byte stops at step 1's `FakeArtifactGateway` — no
function in this module (or in the pipeline components it chains) ever
copies raw content into a ClickHouse row or a citation-intelligence input;
`normalize_citation`'s `raw_url` argument is a citation URL string (a
metadata-shaped value the observed page cites), never the observed page's
own raw bytes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from saena_analytics_clickhouse.rows import CitationRow, ObservationRow
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore
from saena_chatgpt_observer.artifact_gateway import FakeArtifactGateway
from saena_chatgpt_observer.pool import BrowserPool, FixtureBrowserSessionFactory
from saena_chatgpt_observer.pool_capture import PooledObservationResult, run_pooled_observation
from saena_citation_intelligence.service import CitationNormalizationResult, normalize_citation
from saena_domain.execution import JobContext, JobStatus

ENGINE_ID = "chatgpt-search"


def make_job_context(*, tenant_id: str, run_id: str) -> JobContext:
    return JobContext(
        tenant_id=tenant_id,
        workspace_id="ws-w4-13",
        project_id="proj-w4-13",
        run_id=run_id,
        trace_id="b" * 32,
        idempotency_key=f"{tenant_id}:{run_id}:w4-13",
        actor_id="actor-w4-13",
    )


def fixed_clock(instant: str = "2026-07-13T00:00:00Z") -> Callable[[], str]:
    """Return a zero-arg callable that always returns `instant` — deterministic
    `run_pooled_observation(clock=...)` injection (task instruction:
    "Deterministic (inject clock/ids)")."""

    def _clock() -> str:
        return instant

    return _clock


def sequential_observation_ids(prefix: str = "obs") -> Callable[[str, int], str]:
    """Deterministic `observation_id_factory(run_id, index)` callable —
    `{prefix}-{run_id}-{index:04d}`, never a random UUID (determinism
    contract)."""

    def _factory(run_id: str, index: int) -> str:
        return f"{prefix}-{run_id}-{index:04d}"

    return _factory


def opaque_citation_ref(*, tenant_id: str, raw_url: str) -> str:
    """Build the SAME opaque, `uri_ref`-shaped citation ref every call site
    in this module derives from a raw citation URL — `citation://<tenant_id>/
    <sha256_hex(raw_url)>` (mirrors `RawArtifactGatewayPort`'s own
    `artifact://<tenant_id>/<sha256_hex>` opaque-ref discipline). A single
    shared helper so `citation_extractor_for` (step 1, observation-layer
    `citation_refs`) and `run_capture_store_and_normalize_chain` (step 3,
    building each `CitationRow.citation_ref`) always derive the IDENTICAL
    ref for the same `(tenant_id, raw_url)` pair, never two independently
    hand-rolled ref shapes that could silently drift apart."""
    digest = hashlib.sha256(raw_url.encode("utf-8")).hexdigest()
    return f"citation://{tenant_id}/{digest}"


def citation_extractor_for(
    tenant_id: str, url_map: dict[bytes, tuple[str, ...]]
) -> Callable[[bytes], tuple[str, ...]]:
    """Deterministic `CitationExtractor` — maps EXACT raw HTML bytes to a
    fixed tuple of OPAQUE, `uri_ref`-shaped citation refs (see module
    docstring "Field-shape note": `PlatformObservation.citation_refs` is
    `uri_ref`-typed, query strings/fragments forbidden, so this extractor
    never hands back a raw citation URL verbatim). Never derives citations
    from content by parsing (this suite's pool fixture browser responses are
    opaque `bytes`, not real HTML this helper would need to parse —
    citation-intelligence's own URL-derivation logic is out of scope for
    this composite-pipeline suite, which only chains the ALREADY-BUILT
    components)."""

    def _extractor(raw_content: bytes) -> tuple[str, ...]:
        raw_urls = url_map.get(raw_content, ())
        return tuple(opaque_citation_ref(tenant_id=tenant_id, raw_url=url) for url in raw_urls)

    return _extractor


def build_pool(responses: dict[str, bytes], *, max_size: int = 2) -> BrowserPool:
    return BrowserPool(FixtureBrowserSessionFactory(shared_responses=responses), max_size=max_size)


@dataclass(frozen=True, slots=True)
class ObservationChainResult:
    """One query's full chain result: the pooled-capture result, the
    ClickHouse `ObservationRow` actually appended, and every citation
    normalization result derived from that observation's `citation_refs`."""

    pooled: PooledObservationResult
    observation_row: ObservationRow
    citation_normalizations: tuple[CitationNormalizationResult, ...]
    citation_rows: tuple[CitationRow, ...]


@dataclass(frozen=True, slots=True)
class ChainRunResult:
    """`run_capture_store_and_normalize_chain`'s return value: one
    `ObservationChainResult` per query (in order) plus the underlying
    `run_pooled_observation` call's own `final_status` (`JobStatus.
    SUCCEEDED` for a clean run — this helper never swallows a
    `JobStatus.FAILED` run into a chain result, since `run_pooled_
    observation` itself raises before returning on capture failure)."""

    results: tuple[ObservationChainResult, ...]
    final_status: JobStatus


def _query_text_for(pooled: PooledObservationResult, query_texts: Sequence[str], index: int) -> str:
    # `PooledObservationResult` does not itself carry `query_text` (see
    # `pool_capture.py` — the `PlatformObservation` record's own field set
    # is deliberately closed to exactly {tenant_id, run_id, engine_id,
    # observation_id, raw_object_ref, artifact_hash, citation_refs,
    # captured_at}); this helper's own caller supplies the original
    # `queries` sequence positionally instead, index-aligned with
    # `PooledObservationRunResult.results` (`run_pooled_observation` itself
    # iterates `queries` via `enumerate`, so this ordering is guaranteed).
    return query_texts[index]


def run_capture_store_and_normalize_chain(
    *,
    job_context: JobContext,
    queries: Sequence[str],
    responses: dict[str, bytes],
    citation_urls_by_response: dict[bytes, tuple[str, ...]],
    analytics_store: ClickHouseAnalyticsStore,
    tenant_owned_domains: frozenset[str] = frozenset(),
    competitor_domains: frozenset[str] = frozenset(),
    clock_instant: str = "2026-07-13T00:00:00Z",
    engine_id: str = ENGINE_ID,
) -> ChainRunResult:
    """Run the full w4-13 chain for `queries` and return a `ChainRunResult`
    (one `ObservationChainResult` per query, in order, plus the run's own
    `final_status`).

    Step 1 (capture): `run_pooled_observation` against a deterministic
    fixture `BrowserPool` + `FakeArtifactGateway` — raw HTML never leaves
    the gateway; only `raw_object_ref`/`artifact_hash` survive into the
    `PlatformObservation` record. The observation's own `citation_refs` are
    OPAQUE `citation://...` refs (`citation_extractor_for`, `uri_ref`-shaped
    — see module docstring "Field-shape note"), never the raw citation URL
    itself.

    Step 2 (store): each result's `PlatformObservation` record fields are
    projected into an `ObservationRow` (`saena_analytics_clickhouse.rows`)
    and appended to `analytics_store` — a REAL ClickHouse container
    (`conftest.py`'s `analytics_store` fixture). `ObservationRow`'s own
    `__post_init__`/`guard_row_fields` re-validate that no raw content ever
    reaches this step (defense in depth; nothing this helper builds could
    trip that guard, since only ref/hash fields are projected).

    Step 3 (citation normalization): for every RAW (pre-normalization)
    citation URL registered for that query's response in
    `citation_urls_by_response` (position-aligned with the opaque refs step
    1 derived from the SAME list — `opaque_citation_ref` is a pure function
    of `(tenant_id, raw_url)`, so this step re-derives the identical ref
    rather than re-reading it off the record), `normalize_citation` produces
    a `citation.normalized.v1` envelope + `CitationRecord`, and a
    corresponding `CitationRow` is appended to the SAME `analytics_store`.
    """
    pool = build_pool(responses)
    gateway = FakeArtifactGateway()
    extractor = citation_extractor_for(job_context.tenant_id, citation_urls_by_response)

    run_result = run_pooled_observation(
        job_context=job_context,
        pool=pool,
        artifact_gateway=gateway,
        engine_id=engine_id,
        queries=queries,
        citation_extractor=extractor,
        observation_id_factory=sequential_observation_ids(),
        clock=fixed_clock(clock_instant),
    )

    occurred_at = datetime.strptime(clock_instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    chained: list[ObservationChainResult] = []
    for index, pooled in enumerate(run_result.results):
        record = pooled.observation_record
        query_text = _query_text_for(pooled, queries, index)
        observation_row = ObservationRow(
            tenant_id=record["tenant_id"],
            id=record["observation_id"],
            idempotency_key=(
                f"{record['tenant_id']}:{record['run_id']}:{record['observation_id']}"
            ),
            occurred_at=occurred_at,
            engine_id=record["engine_id"],
            run_id=record["run_id"],
            query_text=query_text,
            citation_refs=tuple(record["citation_refs"]),
            raw_object_ref=record["raw_object_ref"],
        )
        analytics_store.append_observation(observation_row)

        raw_urls = citation_urls_by_response.get(responses[query_text], ())
        normalizations: list[CitationNormalizationResult] = []
        citation_rows: list[CitationRow] = []
        for citation_index, raw_url in enumerate(raw_urls):
            citation_id = f"{record['observation_id']}-cite-{citation_index:02d}"
            result = normalize_citation(
                tenant_id=record["tenant_id"],
                run_id=record["run_id"],
                citation_id=citation_id,
                raw_url=raw_url,
                engine_id=record["engine_id"],
                tenant_owned_domains=tenant_owned_domains,
                competitor_domains=competitor_domains,
                clock=fixed_clock(clock_instant),
            )
            normalizations.append(result)

            citation_ref = opaque_citation_ref(tenant_id=record["tenant_id"], raw_url=raw_url)
            citation_row = CitationRow(
                tenant_id=record["tenant_id"],
                id=citation_id,
                idempotency_key=f"{record['tenant_id']}:{record['run_id']}:{citation_id}",
                occurred_at=occurred_at,
                run_id=record["run_id"],
                observation_id=record["observation_id"],
                citation_ref=citation_ref,
                source_domain=result.record.normalized_uri.split("://", 1)[-1].split("/", 1)[0],
                contribution_score=result.record.ownership_confidence,
            )
            analytics_store.append_citation(citation_row)
            citation_rows.append(citation_row)

        chained.append(
            ObservationChainResult(
                pooled=pooled,
                observation_row=observation_row,
                citation_normalizations=tuple(normalizations),
                citation_rows=tuple(citation_rows),
            )
        )

    return ChainRunResult(results=tuple(chained), final_status=run_result.final_status)


__all__ = [
    "ENGINE_ID",
    "ChainRunResult",
    "ObservationChainResult",
    "build_pool",
    "citation_extractor_for",
    "fixed_clock",
    "make_job_context",
    "opaque_citation_ref",
    "run_capture_store_and_normalize_chain",
    "sequential_observation_ids",
]

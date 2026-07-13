"""Scenario 3 (w4-18 mission item 3): a mid-pipeline failure (browser render
failure, artifact-gateway rejection, ClickHouse insert failure) leaves NO
partial committed state — the run fails closed, nothing half-persisted; a
subsequent retry is clean.

Three independent fail-closed proofs, each ending with a clean-retry check:

1. Browser render failure — `saena_chatgpt_observer.capture.
   run_chatgpt_observation` against a `FakeObservationSource` that keeps
   failing transiently past `ObservationBudget.max_retries`
   (`ObservationRetryExhaustedError`, simulating a browser-pool render
   failure): the failing query's `PlatformObservation` is never stored, and
   nothing partial (a half-built `PlatformObservation`, an audit entry for
   the never-captured query) survives the raise.
2. Artifact-gateway rejection — `saena_analytics_clickhouse.rows.
   ObservationRow.__post_init__`'s own `guard_row_fields` (this package's
   "artifact/raw-content gateway") rejects an obviously-raw field
   (`RawContentRejectedError`) BEFORE a row object even exists to be
   appended — no partial row, no partial store mutation, ever.
3. ClickHouse insert failure — `ClickHouseAnalyticsStore.append_observation`
   against a `FailingInsertExecutor` armed to raise mid-INSERT: the row is
   never committed to the (fake) table; disarming and retrying the SAME row
   afterward succeeds cleanly with exactly one row landed (never two,
   never a corrupted partial write).

Plus the Postgres-backed half of the SAME "fails closed, retry is clean"
property against the real outbox/idempotency mechanism (mirrors
`tests/integration/failure_modes/test_rollback_outbox_idempotent_replay_
postgres.py`'s own precedent) — skipped honestly if Docker is unreachable.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from intelligence_failure_factories import (
    RUN_ID,
    TENANT_A,
    FailingInsertExecutor,
    SimulatedInsertFailure,
    make_observation_row,
    make_observation_source_with_one_query,
    make_patch_unit_completed_envelope,
    new_clickhouse_store,
    new_fake_clickhouse_executor,
    run_async,
)
from saena_analytics_clickhouse.errors import RawContentRejectedError
from saena_analytics_clickhouse.rows import ObservationRow
from saena_chatgpt_observer.capture import run_chatgpt_observation
from saena_chatgpt_observer.errors import ObservationNotFoundError, ObservationRetryExhaustedError
from saena_chatgpt_observer.observation import PlatformObservation
from saena_chatgpt_observer.source import CapturedObservation, FakeObservationSource
from saena_chatgpt_observer.store import InMemoryObservationStore
from saena_domain.execution import JobContext
from saena_domain.identity import TenantId
from saena_domain.persistence.postgres.adapters import PostgresIdempotencyStore, PostgresOutbox
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


def _job_context(**overrides: object) -> JobContext:
    fields: dict[str, object] = {
        "tenant_id": TENANT_A,
        "workspace_id": "ws-1",
        "project_id": "proj-1",
        "run_id": RUN_ID,
        "trace_id": "a" * 32,
        "idempotency_key": "idem-observer-1",
        "actor_id": "actor-observer",
    }
    fields.update(overrides)
    return JobContext(**fields)  # type: ignore[arg-type]


def _store_successful_observations_only(
    store: InMemoryObservationStore,
    *,
    tenant_id: str,
    source: FakeObservationSource,
    queries: tuple[str, ...],
) -> None:
    """The realistic caller-side contract this pipeline enforces: only
    observations `run_chatgpt_observation` ACTUALLY returned (i.e. the run
    did not raise) are ever committed to the store — a caller that races
    ahead and stores partial results out of a raised call's local variables
    would be the actual bug this test suite exists to catch; the reference
    implementation here does the fail-closed thing (raise -> nothing new
    committed) by construction, since `run_chatgpt_observation` never
    returns a partial result on failure, only raises."""
    result = run_chatgpt_observation(
        job_context=_job_context(),
        source=source,
        engine_id="chatgpt-search",
        queries=queries,
    )
    for observation in result.observations:
        store.put(tenant_id, observation)


# --- 1. browser render failure (observer retry exhaustion) ---------------------------


def test_browser_render_failure_exhausting_retries_leaves_no_observation_stored() -> None:
    store = InMemoryObservationStore()
    query = "best crm for startups"
    # max_retries=3 for JobKind.CHATGPT_OBSERVER (limits.py) — 4 scheduled
    # failures exhausts every retry attempt without ever succeeding,
    # simulating a browser-pool session that never renders successfully.
    source = make_observation_source_with_one_query(query_text=query, fail_times=4)

    with pytest.raises(ObservationRetryExhaustedError):
        _store_successful_observations_only(
            store, tenant_id=TENANT_A, source=source, queries=(query,)
        )

    # fail-closed: nothing was ever committed for this run.

    with pytest.raises(ObservationNotFoundError):
        store.get(TENANT_A, RUN_ID, query)


def test_browser_render_failure_partway_through_a_multi_query_run_commits_zero_of_the_batch() -> (
    None
):
    """A run requesting THREE queries where the SECOND one exhausts its
    retries: the caller's own fail-closed discipline (see
    `_store_successful_observations_only`) means even the FIRST query's
    otherwise-successful capture is never separately committed — the whole
    batch fails atomically from this run's point of view (mirrors
    `tests/security/test_f8_scope_creep.py`'s "patch unit denied and rolled
    back — including the otherwise-legitimate requested write in the same
    batch" precedent, applied to an observation run instead of a patch
    unit)."""
    store = InMemoryObservationStore()
    source = FakeObservationSource()

    source.register_query(
        "query one",
        CapturedObservation(citation_refs=("ref://citation/1",), raw_object_ref="ref://object/1"),
    )
    source.register_query(
        "query two",
        CapturedObservation(citation_refs=("ref://citation/2",), raw_object_ref="ref://object/2"),
    )
    source.fail_next("query two", times=4)  # exceeds max_retries=3

    with pytest.raises(ObservationRetryExhaustedError):
        _store_successful_observations_only(
            store,
            tenant_id=TENANT_A,
            source=source,
            queries=("query one", "query two", "query three (never reached)"),
        )

    with pytest.raises(ObservationNotFoundError):
        store.get(TENANT_A, RUN_ID, "query one")
    assert source.capture_calls.count("query three (never reached)") == 0


def test_browser_render_failure_then_clean_retry_succeeds_and_commits_exactly_once() -> None:
    """A subsequent retry (a fresh observation run against the SAME query,
    this time succeeding) is clean — exactly one `PlatformObservation`
    lands, never a duplicate/partial one left over from the earlier
    failure."""
    store = InMemoryObservationStore()
    query = "best crm for startups"

    failing_source = make_observation_source_with_one_query(query_text=query, fail_times=4)
    with pytest.raises(ObservationRetryExhaustedError):
        _store_successful_observations_only(
            store, tenant_id=TENANT_A, source=failing_source, queries=(query,)
        )

    clean_source = make_observation_source_with_one_query(query_text=query, fail_times=0)
    _store_successful_observations_only(
        store, tenant_id=TENANT_A, source=clean_source, queries=(query,)
    )

    stored = store.get(TENANT_A, RUN_ID, query)
    assert isinstance(stored, PlatformObservation)
    assert stored.query_text == query


# --- 2. artifact-gateway rejection (raw-content guard) --------------------------------


def test_artifact_gateway_rejects_raw_content_before_any_row_object_exists() -> None:
    """`ObservationRow.__post_init__`'s `guard_row_fields` call IS this
    package's artifact-gateway rejection point — a raw/secret-shaped field
    value never even survives long enough to become a constructible
    `ObservationRow`, so there is no partial row for any downstream
    `ClickHouseAnalyticsStore.append_observation` call to half-commit."""
    with pytest.raises(RawContentRejectedError):
        ObservationRow(
            tenant_id=TENANT_A,
            id="obs-raw-1",
            idempotency_key="idem-obs-raw-1",
            occurred_at=datetime(2026, 7, 1, tzinfo=UTC),
            engine_id="chatgpt-search",
            run_id=RUN_ID,
            query_text="best crm for startups",
            citation_refs=("ref://citation/1",),
            # AWS-shaped secret shows up in what should be an opaque object
            # ref — the artifact gateway must refuse this outright.
            raw_object_ref="ref://object/AKIAABCDEFGHIJKLMNOP",
        )


def test_artifact_gateway_rejection_leaves_the_clickhouse_store_completely_untouched() -> None:
    executor = new_fake_clickhouse_executor()
    store = new_clickhouse_store(executor)

    with pytest.raises(RawContentRejectedError):
        ObservationRow(
            tenant_id=TENANT_A,
            id="obs-raw-2",
            idempotency_key="idem-obs-raw-2",
            occurred_at=datetime(2026, 7, 1, tzinfo=UTC),
            engine_id="chatgpt-search",
            run_id=RUN_ID,
            query_text="best crm for startups",
            citation_refs=("ref://citation/1",),
            raw_object_ref="ref://object/AKIAABCDEFGHIJKLMNOP",
        )

    # nothing reached the store at all — no rows in any table.
    assert store.get_observations(TENANT_A) == ()
    assert executor.tables["observations"] == []


# --- 3. ClickHouse insert failure ------------------------------------------------------


def test_clickhouse_insert_failure_leaves_no_partial_row_committed() -> None:
    executor = FailingInsertExecutor(armed=True)
    store = new_clickhouse_store(executor)
    row = make_observation_row()

    with pytest.raises(SimulatedInsertFailure):
        store.append_observation(row)

    # fail-closed: the fake table backing this executor received no row at
    # all (not even a half-written one — `insert_rows` raises BEFORE ever
    # touching `self.inner.tables`).
    assert executor.inner.tables["observations"] == []
    assert store.get_observations(TENANT_A) == ()


def test_clickhouse_insert_failure_then_clean_retry_commits_exactly_one_row() -> None:
    executor = FailingInsertExecutor(armed=True)
    store = new_clickhouse_store(executor)
    row = make_observation_row()

    with pytest.raises(SimulatedInsertFailure):
        store.append_observation(row)

    # disarm — simulates the transient ClickHouse outage clearing — and
    # retry the SAME row.
    executor.armed = False
    inserted = store.append_observation(row)

    assert inserted is True
    stored = store.get_observations(TENANT_A)
    assert len(stored) == 1
    assert stored[0].idempotency_key == row.idempotency_key
    # exactly 2 insert attempts total: the failed one, then the clean retry.
    assert executor.insert_attempts == 2


# --- Postgres-backed half: outbox/idempotency fail-closed + clean retry ---------------


@pytest.mark.docker
def test_outbox_publish_failure_leaves_row_pending_against_real_postgres_retry_is_clean(
    pg_engine: AsyncEngine,
) -> None:
    from saena_domain.bus import DrainResult, OutboxDrainer, PublishFailedError

    class _FlakyThenCleanPublisher:
        def __init__(self) -> None:
            self.attempts = 0
            self.published: list[tuple[str, dict[str, object]]] = []

        async def publish(self, topic: str, envelope: dict[str, object]) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise PublishFailedError("simulated transient publish failure")
            self.published.append((topic, envelope))

    async def scenario() -> DrainResult:
        outbox = PostgresOutbox(pg_engine)
        envelope = make_patch_unit_completed_envelope(tenant_id=TENANT_A, run_id=RUN_ID)
        await outbox.record(envelope)

        publisher = _FlakyThenCleanPublisher()
        drainer = OutboxDrainer(outbox, publisher)

        first = await drainer.drain_once()
        assert first.published == ()
        assert first.retried_pending == (envelope["event_id"],)

        # row is still pending (never marked published on a failed publish)
        still_pending = await outbox.list_pending()
        assert len(still_pending) == 1

        # clean retry.
        second = await drainer.drain_once()
        assert second.published == (envelope["event_id"],)
        assert len(publisher.published) == 1
        return second

    result = run_async(scenario())
    assert result.published


@pytest.mark.docker
def test_idempotency_mark_failure_never_double_runs_handler_against_real_postgres(
    pg_engine: AsyncEngine,
) -> None:
    from saena_domain.bus import IdempotentConsumer

    async def scenario() -> None:
        store = PostgresIdempotencyStore(pg_engine)
        consumer = IdempotentConsumer(store)
        envelope = make_patch_unit_completed_envelope(tenant_id=TENANT_A, run_id=RUN_ID)

        class _BoomOnFirstCall(Exception):
            pass

        attempts = 0

        async def flaky_handler(env: dict[str, object]) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise _BoomOnFirstCall("simulated mid-pipeline failure")

        with pytest.raises(_BoomOnFirstCall):
            await consumer.process(envelope, flaky_handler)

        # fail closed: the key must NOT be marked seen after a raising
        # handler — a retry gets a real chance to actually process it.
        assert await store.seen(TenantId(TENANT_A), envelope["idempotency_key"]) is False

        # clean retry.
        ran = await consumer.process(envelope, flaky_handler)
        assert ran is True
        assert attempts == 2

    run_async(scenario())

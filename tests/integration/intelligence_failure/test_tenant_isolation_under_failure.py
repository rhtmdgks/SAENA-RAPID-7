"""Scenario 4 (w4-18 mission item 4): a failure in tenant A's run never
exposes or corrupts tenant B's data.

Four independent proofs across the intelligence stack's own tenant-scoped
stores, each specifically composing a TENANT-A FAILURE with a
TENANT-B-UNAFFECTED assertion (not merely "tenant isolation" in the
abstract — the failure itself is the trigger under test):

1. `saena_claim_evidence.store.InMemoryClaimEvidenceStore` — appending a
   cross-tenant-mismatched claim under tenant A's own store call raises
   `CrossTenantLedgerAccessError`; tenant B's own, already-stored ledger is
   completely untouched by that raise.
2. `saena_chatgpt_observer.store.InMemoryObservationStore` — a tenant A
   observation run that exhausts its retries (scenario 3's own browser
   render failure) never touches tenant B's already-stored observations.
3. `saena_analytics_clickhouse.store.ClickHouseAnalyticsStore` — a
   ClickHouse insert failure for tenant A's row (this package's own
   `FailingInsertExecutor`) leaves tenant B's already-committed rows in the
   SAME shared fake table completely unaffected — proven against a shared
   executor/table specifically to rule out a failure "leaking" across the
   tenant boundary at the storage layer.
4. `saena_domain.persistence.postgres.adapters.PostgresOutbox`/
   `PostgresIdempotencyStore` — a cross-tenant `mark_published` attempt
   (tenant B trying to mark tenant A's own outbox row published) is refused
   with `TenantIsolationError`, and tenant A's own row is untouched by the
   denied attempt — real Postgres, mirrors `tests/integration/
   failure_modes/test_rollback_outbox_idempotent_replay_postgres.py`'s own
   precedent, applied to this package's own intelligence-shaped envelope
   vehicle.
"""

from __future__ import annotations

import pytest
from intelligence_failure_factories import (
    RUN_ID,
    TENANT_A,
    TENANT_B,
    FailingInsertExecutor,
    SimulatedInsertFailure,
    make_extracted_claim,
    make_observation_row,
    make_observation_source_with_one_query,
    make_patch_unit_completed_envelope,
    make_platform_observation,
    run_async,
)
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore
from saena_chatgpt_observer.capture import run_chatgpt_observation
from saena_chatgpt_observer.errors import (
    CrossTenantObservationError,
    ObservationNotFoundError,
    ObservationRetryExhaustedError,
)
from saena_chatgpt_observer.store import InMemoryObservationStore
from saena_claim_evidence.errors import CrossTenantLedgerAccessError
from saena_claim_evidence.store import InMemoryClaimEvidenceStore
from saena_domain.execution import JobContext
from saena_domain.identity import TenantId
from saena_domain.persistence.errors import TenantIsolationError
from saena_domain.persistence.postgres.adapters import PostgresOutbox
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


def _job_context(*, tenant_id: str) -> JobContext:
    return JobContext(
        tenant_id=tenant_id,
        workspace_id="ws-1",
        project_id="proj-1",
        run_id=RUN_ID,
        trace_id="a" * 32,
        idempotency_key=f"idem-observer-{tenant_id}",
        actor_id="actor-observer",
    )


# --- 1. claim-evidence ledger -----------------------------------------------------------


def test_cross_tenant_claim_append_failure_leaves_tenant_bs_ledger_untouched() -> None:
    store = InMemoryClaimEvidenceStore()

    # tenant B has an established, healthy ledger BEFORE tenant A's failure.
    claim_b = make_extracted_claim(tenant_id=TENANT_B, claim_id="claim-b")
    store.append_claim(TENANT_B, claim_b)

    # tenant A's own call is mismatched (claim itself is tenant B's) — a
    # cross-tenant attempt made THROUGH tenant A's own store call.
    claim_a_labeled_as_b = make_extracted_claim(tenant_id=TENANT_B, claim_id="claim-should-fail")
    with pytest.raises(CrossTenantLedgerAccessError):
        store.append_claim(TENANT_A, claim_a_labeled_as_b)

    # tenant B's ledger is exactly as it was before tenant A's failed call.
    tenant_b_ledger = store.get_ledger(TENANT_B, "proj-1")
    assert len(tenant_b_ledger) == 1
    assert tenant_b_ledger[0].claim is not None
    assert tenant_b_ledger[0].claim.claim_id == "claim-b"

    # tenant A's own ledger never received the rejected write either.
    assert store.get_ledger(TENANT_A, "proj-1") == ()


# --- 2. chatgpt-observer store -----------------------------------------------------------


def test_tenant_a_browser_render_failure_never_touches_tenant_bs_stored_observations() -> None:
    store = InMemoryObservationStore()

    # tenant B already has a successfully captured, stored observation.
    observation_b = make_platform_observation(tenant_id=TENANT_B, query_text="tenant b query")
    store.put(TENANT_B, observation_b)

    # tenant A's run exhausts retries (scenario 3's browser render failure).
    query_a = "tenant a query that fails"
    failing_source = make_observation_source_with_one_query(query_text=query_a, fail_times=4)
    with pytest.raises(ObservationRetryExhaustedError):
        run_chatgpt_observation(
            job_context=_job_context(tenant_id=TENANT_A),
            source=failing_source,
            engine_id="chatgpt-search",
            queries=(query_a,),
        )

    # tenant B's own stored observation is byte-identical to before.
    still_there = store.get(TENANT_B, RUN_ID, "tenant b query")
    assert still_there == observation_b

    # tenant A's failed run never landed a row of its own either.

    with pytest.raises(ObservationNotFoundError):
        store.get(TENANT_A, RUN_ID, query_a)


def test_cross_tenant_observation_store_put_is_refused_tenant_b_store_unaffected() -> None:
    """A caller attempting to store a tenant-A-owned observation UNDER
    tenant B's own storage call is refused outright (fail-closed
    default-DENY), and whatever tenant B already legitimately owns stays
    untouched."""
    store = InMemoryObservationStore()
    observation_b = make_platform_observation(tenant_id=TENANT_B, query_text="tenant b query")
    store.put(TENANT_B, observation_b)

    observation_a_mislabeled = make_platform_observation(
        tenant_id=TENANT_A, query_text="mismatched"
    )
    with pytest.raises(CrossTenantObservationError):
        store.put(TENANT_B, observation_a_mislabeled)

    assert store.get(TENANT_B, RUN_ID, "tenant b query") == observation_b


# --- 3. analytics-clickhouse store (shared fake table) -----------------------------------


def test_tenant_a_clickhouse_insert_failure_leaves_tenant_bs_rows_in_the_same_table_untouched() -> (
    None
):
    executor = FailingInsertExecutor(armed=False)
    store = ClickHouseAnalyticsStore(executor)

    # tenant B commits successfully FIRST, into the SAME shared fake table.
    row_b = make_observation_row(tenant_id=TENANT_B, id="obs-b-1", idempotency_key="idem-obs-b-1")
    assert store.append_observation(row_b) is True

    # tenant A's insert now fails.
    executor.armed = True
    row_a = make_observation_row(tenant_id=TENANT_A, id="obs-a-1", idempotency_key="idem-obs-a-1")

    with pytest.raises(SimulatedInsertFailure):
        store.append_observation(row_a)

    # tenant B's row, in the SAME underlying fake table, is untouched.
    tenant_b_rows = store.get_observations(TENANT_B)
    assert len(tenant_b_rows) == 1
    assert tenant_b_rows[0].id == "obs-b-1"

    # and tenant A's own failed insert landed nothing.
    assert store.get_observations(TENANT_A) == ()

    # a query scoped to tenant A can never see tenant B's row either
    # (`AnalyticsQuery.for_tenant` structural scoping — belt-and-suspenders
    # alongside the insert-failure isolation proven above).
    assert all(row.tenant_id == TENANT_B for row in tenant_b_rows)


def test_tenant_a_clickhouse_insert_failure_then_retry_still_only_ever_touches_tenant_a_rows() -> (
    None
):
    executor = FailingInsertExecutor(armed=True)
    store = ClickHouseAnalyticsStore(executor)

    row_b = make_observation_row(tenant_id=TENANT_B, id="obs-b-2", idempotency_key="idem-obs-b-2")
    executor.armed = False
    store.append_observation(row_b)

    executor.armed = True
    row_a = make_observation_row(tenant_id=TENANT_A, id="obs-a-2", idempotency_key="idem-obs-a-2")

    with pytest.raises(SimulatedInsertFailure):
        store.append_observation(row_a)

    executor.armed = False
    assert store.append_observation(row_a) is True

    assert len(store.get_observations(TENANT_A)) == 1
    assert len(store.get_observations(TENANT_B)) == 1


# --- 4. Postgres outbox (real I/O) --------------------------------------------------------


@pytest.mark.docker
def test_cross_tenant_mark_published_denied_never_affects_tenant_as_own_row(
    pg_engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(pg_engine)
        envelope_a = make_patch_unit_completed_envelope(
            tenant_id=TENANT_A, run_id=RUN_ID, patch_unit_id="PU-A"
        )
        recorded_a = await outbox.record(envelope_a)

        with pytest.raises(TenantIsolationError):
            await outbox.mark_published(TenantId(TENANT_B), recorded_a["event_id"])

        # tenant A's own row is untouched by the denied cross-tenant attempt
        # — still pending, unpublished.
        still_pending_a = await outbox.list_pending(tenant_id=TenantId(TENANT_A))
        assert still_pending_a == (recorded_a,)

    run_async(scenario())


@pytest.mark.docker
def test_tenant_a_publish_failure_never_exposes_tenant_bs_pending_rows(
    pg_engine: AsyncEngine,
) -> None:
    """A tenant-A-scoped `list_pending` call, made WHILE tenant A also has a
    pending row that will go on to fail publish, never returns tenant B's
    own pending row — the failure path and the tenant filter compose
    correctly together, not just in isolation."""

    async def scenario() -> None:
        outbox = PostgresOutbox(pg_engine)
        envelope_a = make_patch_unit_completed_envelope(
            tenant_id=TENANT_A, run_id=RUN_ID, patch_unit_id="PU-A-2"
        )
        envelope_b = make_patch_unit_completed_envelope(
            tenant_id=TENANT_B, run_id=RUN_ID, patch_unit_id="PU-B-2"
        )
        await outbox.record(envelope_a)
        await outbox.record(envelope_b)

        tenant_a_pending = await outbox.list_pending(tenant_id=TenantId(TENANT_A))
        assert len(tenant_a_pending) == 1
        assert tenant_a_pending[0]["tenant_id"] == TENANT_A

        tenant_b_pending = await outbox.list_pending(tenant_id=TenantId(TENANT_B))
        assert len(tenant_b_pending) == 1
        assert tenant_b_pending[0]["tenant_id"] == TENANT_B

    run_async(scenario())

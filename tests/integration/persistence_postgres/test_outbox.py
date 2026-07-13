"""Integration tests for `PostgresOutbox` — mirrors `InMemoryOutbox`'s
reference semantics (`tests/unit/domain_persistence/test_outbox.py`) over
real SQL, plus a transactional-outbox pattern test (W2A requirement: outbox
`record` sharing the SAME connection/transaction as an accompanying state
change, and rolling back together on failure)."""

from __future__ import annotations

import pytest
from postgres_factories import make_system_envelope, make_tenant_envelope, run_async
from saena_domain.audit import ForbiddenAuditDataError
from saena_domain.identity import TenantId
from saena_domain.persistence.errors import (
    NotFoundError,
    OutboxValidationError,
    TenantIsolationError,
)
from saena_domain.persistence.postgres.adapters import PostgresArtifactManifestStore, PostgresOutbox
from saena_domain.persistence.postgres.tables import outbox as outbox_table
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

TENANT_A = TenantId("acme-co")
TENANT_B = TenantId("globex-co")


def test_record_then_list_pending_round_trips(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_tenant_envelope()

        stored = await outbox.record(envelope)

        assert stored == envelope
        assert await outbox.list_pending(TENANT_A) == (envelope,)

    run_async(scenario())


def test_record_rejects_invalid_envelope_shape(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        with pytest.raises(OutboxValidationError):
            await outbox.record({"not": "an envelope"})

    run_async(scenario())


def test_record_rejects_envelope_missing_required_field(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_tenant_envelope()
        del envelope["trace_id"]

        with pytest.raises(OutboxValidationError):
            await outbox.record(envelope)

    run_async(scenario())


def test_record_dedups_identical_envelope_by_event_id(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_tenant_envelope()

        first = await outbox.record(envelope)
        second = await outbox.record(dict(envelope))

        assert first == second
        assert len(await outbox.list_pending(TENANT_A)) == 1

    run_async(scenario())


def test_record_rejects_same_event_id_different_content(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_tenant_envelope()
        await outbox.record(envelope)
        conflicting = dict(envelope)
        conflicting["idempotency_key"] = "different-key"

        with pytest.raises(OutboxValidationError):
            await outbox.record(conflicting)

    run_async(scenario())


def test_mark_published_removes_from_pending(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_tenant_envelope()
        await outbox.record(envelope)

        await outbox.mark_published(TENANT_A, envelope["event_id"])

        assert await outbox.list_pending(TENANT_A) == ()

    run_async(scenario())


def test_mark_published_missing_event_id_raises_not_found(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        with pytest.raises(NotFoundError):
            await outbox.mark_published(TENANT_A, "nonexistent-event-id")

    run_async(scenario())


def test_mark_published_cross_tenant_denied_direction_a_to_b(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope_a = make_tenant_envelope(tenant_id="acme-co", run_id="run-a")
        await outbox.record(envelope_a)

        with pytest.raises(TenantIsolationError):
            await outbox.mark_published(TENANT_B, envelope_a["event_id"])

        assert await outbox.list_pending(TENANT_A) == (envelope_a,)

    run_async(scenario())


def test_mark_published_cross_tenant_denied_direction_b_to_a(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope_b = make_tenant_envelope(
            tenant_id="globex-co",
            run_id="run-b",
            idempotency_key="globex-co:run-b:patch-unit-1",
        )
        await outbox.record(envelope_b)

        with pytest.raises(TenantIsolationError):
            await outbox.mark_published(TENANT_A, envelope_b["event_id"])

        assert await outbox.list_pending(TENANT_B) == (envelope_b,)

    run_async(scenario())


def test_mark_published_system_envelope_requires_none_tenant_id(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_system_envelope()
        await outbox.record(envelope)

        with pytest.raises(TenantIsolationError):
            await outbox.mark_published(TENANT_A, envelope["event_id"])

        await outbox.mark_published(None, envelope["event_id"])
        assert await outbox.list_pending() == ()

    run_async(scenario())


def test_mark_published_tenant_envelope_rejects_none_tenant_id(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_tenant_envelope()
        await outbox.record(envelope)

        with pytest.raises(TenantIsolationError):
            await outbox.mark_published(None, envelope["event_id"])

    run_async(scenario())


def test_list_pending_filters_by_tenant(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope_a = make_tenant_envelope(tenant_id="acme-co", run_id="run-a")
        envelope_b = make_tenant_envelope(
            tenant_id="globex-co",
            run_id="run-b",
            idempotency_key="globex-co:run-b:patch-unit-1",
        )
        await outbox.record(envelope_a)
        await outbox.record(envelope_b)

        pending_a = await outbox.list_pending(TenantId("acme-co"))

        assert pending_a == (envelope_a,)

    run_async(scenario())


def test_list_pending_none_returns_every_tenant(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope_a = make_tenant_envelope(tenant_id="acme-co", run_id="run-a")
        envelope_b = make_tenant_envelope(
            tenant_id="globex-co",
            run_id="run-b",
            idempotency_key="globex-co:run-b:patch-unit-1",
        )
        await outbox.record(envelope_a)
        await outbox.record(envelope_b)

        pending = await outbox.list_pending()

        assert {e["event_id"] for e in pending} == {envelope_a["event_id"], envelope_b["event_id"]}

    run_async(scenario())


def test_record_rejects_forbidden_data_in_payload(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_tenant_envelope(
            producer="demand-graph-service",
            event_type="demand.graph.versioned.v1",
            idempotency_key="acme-co:run-2026-0712-0013:demand-graph-v1",
            payload={"password": "hunter2"},
        )

        with pytest.raises(ForbiddenAuditDataError):
            await outbox.record(envelope)

    run_async(scenario())


def test_record_return_value_mutation_does_not_corrupt_store(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_tenant_envelope()

        stored = await outbox.record(envelope)
        stored["payload"]["patch_unit_id"] = "TAMPERED"

        pending = await outbox.list_pending(TENANT_A)
        assert pending[0]["payload"]["patch_unit_id"] == "w2-13-postgres"

    run_async(scenario())


def test_transactional_outbox_pattern_shares_connection_with_state_change(
    engine: AsyncEngine,
) -> None:
    """W2A requirement: an outbox `record` call sharing the SAME
    `AsyncConnection`/transaction as an accompanying state change (here, an
    artifact manifest `put`) commits or rolls back TOGETHER — a crash/error
    between the two can never leave one persisted without the other.

    Both the commit and rollback scenarios run inside ONE
    `asyncio.run(scenario())` call (see module docstring "Event-loop-per-test
    discipline" in `conftest.py`) rather than two separate `run_async` calls
    — reusing the same `engine` fixture's connection pool across two
    DIFFERENT `asyncio.run()`-opened event loops hits the exact cross-loop
    `asyncpg` connection problem that fixture's own docstring documents.
    """

    async def scenario() -> None:
        manifest_store = PostgresArtifactManifestStore(engine)
        outbox = PostgresOutbox(engine)

        # --- commits together ---
        commit_envelope = make_tenant_envelope(idempotency_key="acme-co:run-a:txn-outbox-commit")
        async with engine.begin() as conn:
            await manifest_store.put(
                TENANT_A, "patch-unit-txn", "commit-txn", {"ok": True}, connection=conn
            )
            await outbox.record(commit_envelope, connection=conn)

        stored_manifest = await manifest_store.get(TENANT_A, "patch-unit-txn", "commit-txn")
        assert stored_manifest == {"ok": True}
        pending = await outbox.list_pending(TENANT_A)
        assert commit_envelope in pending

        # --- rolls back together ---
        rollback_envelope = make_tenant_envelope(
            idempotency_key="acme-co:run-a:txn-outbox-rollback"
        )
        try:
            async with engine.begin() as conn:
                await manifest_store.put(
                    TENANT_A, "patch-unit-txn-2", "commit-txn-2", {"ok": True}, connection=conn
                )
                await outbox.record(rollback_envelope, connection=conn)
                raise RuntimeError("simulated failure after both writes, before commit")
        except RuntimeError:
            pass

        # Neither landed — the shared transaction rolled back both writes.
        with pytest.raises(NotFoundError):
            await manifest_store.get(TENANT_A, "patch-unit-txn-2", "commit-txn-2")
        pending = await outbox.list_pending(TENANT_A)
        assert rollback_envelope not in pending

    run_async(scenario())


def test_outbox_event_id_unique_enforced_structurally(engine: AsyncEngine) -> None:
    """Raw SQL bypassing the adapter's own dedup check: a second row with the
    SAME `event_id` violates the table's own primary key."""

    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_tenant_envelope()
        await outbox.record(envelope)

        async with engine.begin() as conn:
            with pytest.raises(IntegrityError):
                await conn.execute(
                    outbox_table.insert().values(
                        event_id=envelope["event_id"],
                        owner_tenant_id="globex-co",
                        context_type="tenant",
                        envelope={"different": "payload"},
                        published=False,
                    )
                )

    run_async(scenario())


def test_pending_query_reads_owner_tenant_id_column(engine: AsyncEngine) -> None:
    """Sanity check that `owner_tenant_id` is populated correctly for a
    tenant-context envelope (used by `list_pending`'s tenant filter)."""

    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_tenant_envelope()
        await outbox.record(envelope)

        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    select(outbox_table.c.owner_tenant_id).where(
                        outbox_table.c.event_id == envelope["event_id"]
                    )
                )
            ).first()
            assert row is not None
            assert row[0] == "acme-co"

    run_async(scenario())

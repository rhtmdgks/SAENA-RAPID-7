"""Rollback verification gate (testing-strategy.md sec F-7), REAL Postgres
half: "workflow retry/replay", "duplicate-event dedup", "outbox replay",
"tenant isolation on rollback" against `saena_domain.persistence.postgres.
adapters.PostgresOutbox` / `PostgresIdempotencyStore` (real SQL, real
`postgres:16-alpine` testcontainer) + the REAL `saena_domain.bus.
IdempotentConsumer`/`OutboxDrainer` orchestration on top of them.

Pure in-memory proof of the SAME mechanism lives in `tests/security/
test_rollback_idempotency_and_outbox_replay.py` — this module is the same
narrative (a patch unit fails once, is retried, succeeds, and that single
success must survive at-least-once redelivery/replay without duplicating)
against the real persistence layer instead of `InMemoryOutbox`/
`InMemoryIdempotencyStore`.
"""

from __future__ import annotations

import pytest
from failure_modes_postgres_factories import (
    TENANT_A,
    TENANT_B,
    TenantId,
    make_patch_unit_completed_envelope,
    run_async,
)
from saena_domain.bus import IdempotentConsumer, InMemoryPublisher, OutboxDrainer
from saena_domain.persistence.errors import TenantIsolationError
from saena_domain.persistence.postgres.adapters import PostgresIdempotencyStore, PostgresOutbox
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


def test_retried_success_envelope_redelivered_twice_against_real_postgres_runs_once(
    engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        store = PostgresIdempotencyStore(engine)
        consumer = IdempotentConsumer(store)
        envelope = make_patch_unit_completed_envelope(tenant_id=TENANT_A)
        handled: list[dict[str, object]] = []

        async def handler(env: dict[str, object]) -> None:
            handled.append(env)

        first_ran = await consumer.process(envelope, handler)
        second_ran = await consumer.process(dict(envelope), handler)

        assert first_ran is True
        assert second_ran is False
        assert len(handled) == 1
        assert await store.seen(TenantId(TENANT_A), envelope["idempotency_key"])

    run_async(scenario())


def test_outbox_drain_against_real_postgres_never_republishes_a_published_row(
    engine: AsyncEngine,
) -> None:
    publisher = InMemoryPublisher()

    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_patch_unit_completed_envelope(tenant_id=TENANT_A)
        await outbox.record(envelope)

        drainer = OutboxDrainer(outbox, publisher)

        first_drain = await drainer.drain_once()
        assert first_drain.published == (envelope["event_id"],)

        # a retried/replayed drain (e.g. a Temporal activity retry re-running
        # the same drain step) must find nothing pending.
        second_drain = await drainer.drain_once()
        assert second_drain.published == ()
        assert second_drain.retried_pending == ()

        remaining_pending = await outbox.list_pending(tenant_id=TenantId(TENANT_A))
        assert remaining_pending == ()

    run_async(scenario())
    assert len(publisher.published) == 1, "exactly one publish reached the broker"


def test_cross_tenant_mark_published_denied_against_real_postgres(engine: AsyncEngine) -> None:
    """ "other tenants unaffected": tenant B can never mark tenant A's own
    outbox row published — real Postgres `TenantIsolationError`, not merely
    an in-memory convention."""

    async def scenario() -> None:
        outbox = PostgresOutbox(engine)
        envelope = make_patch_unit_completed_envelope(tenant_id=TENANT_A)
        recorded = await outbox.record(envelope)

        with pytest.raises(TenantIsolationError):
            await outbox.mark_published(TenantId(TENANT_B), recorded["event_id"])

        # tenant A's own row is untouched by the denied cross-tenant attempt.
        still_pending = await outbox.list_pending(tenant_id=TenantId(TENANT_A))
        assert still_pending == (recorded,)

    run_async(scenario())

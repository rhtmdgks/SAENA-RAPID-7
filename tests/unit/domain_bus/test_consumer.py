"""Tests for `saena_domain.bus.consumer.IdempotentConsumer`."""

from __future__ import annotations

import asyncio
import contextlib

from bus_factories import (
    FakePostgresIdempotencyStore,
    make_aggregate_envelope,
    make_system_envelope,
    make_tenant_envelope,
)
from saena_domain.bus.consumer import SYSTEM_SCOPE_TENANT_ID, IdempotentConsumer
from saena_domain.identity import TenantId
from saena_domain.persistence import InMemoryIdempotencyStore

TENANT_A = TenantId("acme-co")


def test_first_delivery_runs_handler_and_marks_seen() -> None:
    store = InMemoryIdempotencyStore()
    consumer = IdempotentConsumer(store)
    envelope = make_tenant_envelope()
    calls: list[dict] = []

    async def handler(env: dict) -> None:
        calls.append(env)

    ran = asyncio.run(consumer.process(envelope, handler))

    assert ran is True
    assert calls == [envelope]
    assert store.seen(TENANT_A, envelope["idempotency_key"]) is True


def test_redelivery_skips_handler() -> None:
    store = InMemoryIdempotencyStore()
    consumer = IdempotentConsumer(store)
    envelope = make_tenant_envelope()
    calls: list[dict] = []

    async def handler(env: dict) -> None:
        calls.append(env)

    async def scenario() -> tuple[bool, bool]:
        first = await consumer.process(envelope, handler)
        second = await consumer.process(envelope, handler)
        return first, second

    first_ran, second_ran = asyncio.run(scenario())

    assert first_ran is True
    assert second_ran is False
    # Handler ran exactly once despite two deliveries of the same envelope.
    assert len(calls) == 1


def test_handler_exception_leaves_key_unmarked_for_retry() -> None:
    store = InMemoryIdempotencyStore()
    consumer = IdempotentConsumer(store)
    envelope = make_tenant_envelope()

    async def failing_handler(_: dict) -> None:
        raise RuntimeError("boom")

    async def ok_handler(_: dict) -> None:
        return None

    async def scenario() -> bool:
        with contextlib.suppress(RuntimeError):
            await consumer.process(envelope, failing_handler)
        # Key must be unmarked — retry gets a real chance to process.
        return await consumer.process(envelope, ok_handler)

    ran_on_retry = asyncio.run(scenario())

    assert ran_on_retry is True


def test_system_envelope_uses_system_scope_dedup_namespace() -> None:
    store = InMemoryIdempotencyStore()
    consumer = IdempotentConsumer(store)
    envelope = make_system_envelope()

    async def handler(_: dict) -> None:
        return None

    asyncio.run(consumer.process(envelope, handler))

    assert store.seen(SYSTEM_SCOPE_TENANT_ID, envelope["idempotency_key"]) is True
    assert store.seen(TENANT_A, envelope["idempotency_key"]) is False


def test_aggregate_envelope_uses_system_scope_dedup_namespace() -> None:
    store = InMemoryIdempotencyStore()
    consumer = IdempotentConsumer(store)
    envelope = make_aggregate_envelope()

    async def handler(_: dict) -> None:
        return None

    asyncio.run(consumer.process(envelope, handler))

    assert store.seen(SYSTEM_SCOPE_TENANT_ID, envelope["idempotency_key"]) is True


def test_async_store_handler_runs_exactly_once_and_mark_is_awaited() -> None:
    """Critic MUST-FIX (w2-18 review): against an ASYNC `IdempotencyStore`
    (`PostgresIdempotencyStore`-shaped — `seen`/`mark` are coroutines, not
    plain sync methods), the handler must actually run on first delivery
    (not be silently skipped because an un-awaited coroutine object is
    always truthy), and `mark` must be genuinely awaited (not left as a
    dangling `RuntimeWarning: coroutine was never awaited`)."""
    store = FakePostgresIdempotencyStore()
    consumer = IdempotentConsumer(store)
    envelope = make_tenant_envelope()
    calls: list[dict] = []

    async def handler(env: dict) -> None:
        calls.append(env)

    ran = asyncio.run(consumer.process(envelope, handler))

    assert ran is True
    assert len(calls) == 1
    # mark() was actually awaited (not left as a dangling coroutine) — its
    # side effect (appending to mark_calls / adding to the internal set) is
    # only observable if the coroutine body actually ran to completion.
    assert store.mark_calls == [(TENANT_A.value, envelope["idempotency_key"])]


def test_async_store_redelivery_still_skips_handler() -> None:
    """Same async-store double, second delivery of the SAME envelope: proves
    `seen()`'s coroutine result is correctly awaited and interpreted (not
    treated as always-truthy) BOTH on the first (not-yet-seen) and second
    (now-seen) call."""
    store = FakePostgresIdempotencyStore()
    consumer = IdempotentConsumer(store)
    envelope = make_tenant_envelope()
    calls: list[dict] = []

    async def handler(env: dict) -> None:
        calls.append(env)

    async def scenario() -> tuple[bool, bool]:
        first = await consumer.process(envelope, handler)
        second = await consumer.process(envelope, handler)
        return first, second

    first_ran, second_ran = asyncio.run(scenario())

    assert first_ran is True
    assert second_ran is False
    assert len(calls) == 1
    assert store.mark_calls == [(TENANT_A.value, envelope["idempotency_key"])]


def test_two_different_tenants_have_independent_dedup_scopes() -> None:
    store = InMemoryIdempotencyStore()
    consumer = IdempotentConsumer(store)
    envelope_a = make_tenant_envelope(tenant_id="acme-co", run_id="run-a")
    envelope_b = make_tenant_envelope(
        tenant_id="globex-co",
        run_id="run-b",
        idempotency_key=envelope_a["idempotency_key"],  # same key, different tenant
    )

    calls: list[dict] = []

    async def handler(env: dict) -> None:
        calls.append(env)

    async def scenario() -> tuple[bool, bool]:
        ran_a = await consumer.process(envelope_a, handler)
        ran_b = await consumer.process(envelope_b, handler)
        return ran_a, ran_b

    ran_a, ran_b = asyncio.run(scenario())

    assert ran_a is True
    assert ran_b is True
    assert len(calls) == 2

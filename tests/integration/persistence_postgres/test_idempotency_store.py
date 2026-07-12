"""Integration tests for `PostgresIdempotencyStore` — mirrors
`InMemoryIdempotencyStore`'s reference semantics
(`tests/unit/domain_persistence/test_idempotency_store.py`) over real SQL."""

from __future__ import annotations

import pytest
from postgres_factories import run_async
from saena_domain.identity import TenantId
from saena_domain.persistence.postgres.adapters import PostgresIdempotencyStore
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

TENANT_A = TenantId("acme-co")
TENANT_B = TenantId("globex-co")


def test_seen_false_before_mark(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresIdempotencyStore(engine)
        assert await store.seen(TENANT_A, "key-1") is False

    run_async(scenario())


def test_mark_then_seen_true(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresIdempotencyStore(engine)
        await store.mark(TENANT_A, "key-1")

        assert await store.seen(TENANT_A, "key-1") is True

    run_async(scenario())


def test_mark_twice_is_idempotent_no_op(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresIdempotencyStore(engine)
        await store.mark(TENANT_A, "key-1")
        await store.mark(TENANT_A, "key-1")  # must not raise

        assert await store.seen(TENANT_A, "key-1") is True

    run_async(scenario())


def test_seen_is_scoped_per_tenant(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresIdempotencyStore(engine)
        await store.mark(TENANT_A, "key-1")

        assert await store.seen(TENANT_A, "key-1") is True
        assert await store.seen(TENANT_B, "key-1") is False

    run_async(scenario())


def test_caller_injected_connection_used_for_mark_and_seen(engine: AsyncEngine) -> None:
    """`mark`/`seen` also accept a caller-supplied `connection=` (session-scoped
    variant, `adapters.py`'s module docstring)."""

    async def scenario() -> None:
        store = PostgresIdempotencyStore(engine)

        async with engine.begin() as conn:
            await store.mark(TENANT_A, "key-injected", connection=conn)
            assert await store.seen(TENANT_A, "key-injected", connection=conn) is True

    run_async(scenario())

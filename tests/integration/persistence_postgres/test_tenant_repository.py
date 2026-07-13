"""Integration tests for `PostgresTenantRepository` against a real Postgres
testcontainer (ADR-0017) — mirrors `InMemoryTenantRepository`'s reference
semantics (`tests/unit/domain_persistence/test_tenant_repository.py`) but
over real SQL, plus a raw-SQL discriminator-enforcement test that has no
in-memory equivalent (Postgres alone can enforce a NOT NULL column)."""

from __future__ import annotations

import pytest
from postgres_factories import make_tenant_context, run_async
from saena_domain.identity import TenantId, TenantSuspendedError
from saena_domain.persistence.errors import NotFoundError
from saena_domain.persistence.postgres.adapters import PostgresTenantRepository
from saena_domain.persistence.postgres.tables import tenants
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

TENANT_A = TenantId("acme-co")


def test_put_then_get_round_trips(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresTenantRepository(engine)
        context = make_tenant_context()

        await repo.put(TENANT_A, context)
        fetched = await repo.get(TENANT_A)

        assert fetched.tenant_id.value == "acme-co"
        assert fetched.status == "active"

    run_async(scenario())


def test_get_missing_tenant_raises_not_found(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresTenantRepository(engine)
        with pytest.raises(NotFoundError):
            await repo.get(TenantId("no-such-tenant"))

    run_async(scenario())


def test_put_rejects_mismatched_context_tenant_id(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresTenantRepository(engine)
        context = make_tenant_context(tenant_id="globex-co", namespace="saena-tenant-globex-co")
        with pytest.raises(ValueError, match="does not match"):
            await repo.put(TENANT_A, context)

    run_async(scenario())


def test_put_is_upsert_by_tenant_id(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresTenantRepository(engine)
        await repo.put(TENANT_A, make_tenant_context(policy_version="1.0.0"))
        await repo.put(TENANT_A, make_tenant_context(policy_version="2.0.0"))

        fetched = await repo.get(TENANT_A)
        assert fetched.model.policy_version.root == "2.0.0"

    run_async(scenario())


def test_get_record_is_gate_free_for_suspended_tenant(engine: AsyncEngine) -> None:
    """Critic MUST-FIX 4 parity: `get_record` observes a suspended tenant
    without raising `TenantSuspendedError`, unlike `get`."""

    async def scenario() -> None:
        repo = PostgresTenantRepository(engine)
        await repo.put(TENANT_A, make_tenant_context())
        await repo.update_status(TENANT_A, "suspended")

        record = await repo.get_record(TENANT_A)
        assert record.status == "suspended"
        assert record.raw_payload["tenant_id"] == "acme-co"

        with pytest.raises(TenantSuspendedError):
            await repo.get(TENANT_A)

    run_async(scenario())


def test_update_status_lands_regardless_of_new_status(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresTenantRepository(engine)
        await repo.put(TENANT_A, make_tenant_context())

        result = await repo.update_status(TENANT_A, "terminating")

        assert result == "terminating"
        record = await repo.get_record(TENANT_A)
        assert record.status == "terminating"

    run_async(scenario())


def test_update_status_missing_tenant_raises_not_found(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresTenantRepository(engine)
        with pytest.raises(NotFoundError):
            await repo.update_status(TenantId("no-such-tenant"), "suspended")

    run_async(scenario())


def test_get_record_missing_tenant_raises_not_found(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresTenantRepository(engine)
        with pytest.raises(NotFoundError):
            await repo.get_record(TenantId("no-such-tenant"))

    run_async(scenario())


def test_get_record_raw_payload_is_defensive_copy(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresTenantRepository(engine)
        await repo.put(TENANT_A, make_tenant_context())

        record = await repo.get_record(TENANT_A)
        with pytest.raises(TypeError):
            record.raw_payload["status"] = "TAMPERED"  # MappingProxyType is read-only

        # A second read is unaffected regardless.
        record_again = await repo.get_record(TENANT_A)
        assert record_again.status == "active"

    run_async(scenario())


def test_caller_injected_connection_used_for_put_get_and_update_status(engine: AsyncEngine) -> None:
    """Every method also accepts a caller-supplied `connection=` (the
    session-scoped-transaction variant, `adapters.py`'s own "Async,
    connection/session-injectable" module docstring) — exercised here for
    `put`/`get`/`update_status` together inside ONE shared, explicitly
    committed transaction."""

    async def scenario() -> None:
        repo = PostgresTenantRepository(engine)
        context = make_tenant_context()

        async with engine.begin() as conn:
            await repo.put(TENANT_A, context, connection=conn)
            fetched = await repo.get(TENANT_A, connection=conn)
            assert fetched.status == "active"
            new_status = await repo.update_status(TENANT_A, "suspended", connection=conn)
            assert new_status == "suspended"

        record = await repo.get_record(TENANT_A)
        assert record.status == "suspended"

    run_async(scenario())


def test_tenant_id_discriminator_enforced_structurally(engine: AsyncEngine) -> None:
    """Raw SQL bypassing the adapter: inserting a row with `tenant_id=NULL`
    violates the NOT NULL primary-key column (ADR-0007/ADR-0014
    discriminator enforced by schema, not just application code)."""

    async def scenario() -> None:
        async with engine.begin() as conn:
            with pytest.raises(IntegrityError):
                await conn.execute(
                    tenants.insert().values(
                        tenant_id=None, status="active", payload={"tenant_id": "x"}
                    )
                )

    run_async(scenario())

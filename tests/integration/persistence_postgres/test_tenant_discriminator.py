"""Cross-cutting structural test: EVERY tenant-scoped table this patch unit
owns has a `tenant_id` column that is `NOT NULL` and participates in the
primary key — inserting a row with `tenant_id=NULL` (or omitted) must fail
at the database level, never merely at the adapter's application-code level
(ADR-0007 "Postgres = schema-per-capability + tenant_id 인덱스/RLS(2차 방어)",
ADR-0014 discriminator). This is checked with RAW SQL inserts, bypassing
every adapter, precisely because the point is to prove the SCHEMA itself
enforces the discriminator, not just the Python code sitting in front of
it."""

from __future__ import annotations

import pytest
from postgres_factories import run_async
from saena_domain.persistence.postgres.tables import (
    artifact_manifests,
    idempotency_keys,
    plan_decisions,
    plans,
    tenants,
)
from sqlalchemy import Table
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

# audit_entries/outbox are intentionally excluded here: audit_entries'
# tenant_id is NULLABLE by design (system-scope rows carry tenant_id=NULL,
# see tables.py's own docstring — `scope_key` is the enforced discriminator
# column there, not `tenant_id` directly); outbox's `owner_tenant_id` is
# likewise nullable for system/aggregate-context envelopes. Both still
# enforce a NOT NULL `scope_key`/`event_id` PK component instead — see
# `test_audit_ledger.py`/`test_outbox.py` for those tables' own coverage.

_TENANT_SCOPED_TABLES_MINIMAL_ROWS = [
    (tenants, {"status": "active", "payload": {}}),
    (plans, {"contract_hash": "sha256:x", "content_fingerprint": "fp"}),
    (
        plan_decisions,
        {
            "contract_hash": "sha256:x",
            "approver_actor_id": "approver-1",
            "decision": "approved",
            "proposer_actor_id": "proposer-1",
            "high_risk": False,
            "decided_at": "2026-07-13T00:00:00Z",
        },
    ),
    (
        artifact_manifests,
        {"patch_unit_id": "pu-1", "worktree_commit": "c1", "manifest": {}},
    ),
    (idempotency_keys, {"idempotency_key": "k-1"}),
]


@pytest.mark.parametrize(
    "table,row_without_tenant_id",
    _TENANT_SCOPED_TABLES_MINIMAL_ROWS,
    ids=[t.name for t, _ in _TENANT_SCOPED_TABLES_MINIMAL_ROWS],
)
def test_tenant_id_not_null_enforced_at_schema_level(
    engine: AsyncEngine, table: Table, row_without_tenant_id: dict[str, object]
) -> None:
    async def scenario() -> None:
        async with engine.begin() as conn:
            with pytest.raises(IntegrityError):
                await conn.execute(table.insert().values(tenant_id=None, **row_without_tenant_id))

    run_async(scenario())


@pytest.mark.parametrize(
    "table,row_without_tenant_id",
    _TENANT_SCOPED_TABLES_MINIMAL_ROWS,
    ids=[t.name for t, _ in _TENANT_SCOPED_TABLES_MINIMAL_ROWS],
)
def test_tenant_id_omitted_entirely_also_rejected(
    engine: AsyncEngine, table: Table, row_without_tenant_id: dict[str, object]
) -> None:
    """Same as above but via omitting the column entirely rather than
    passing an explicit `None` — proves there is no column default that
    would let a caller sidestep the NOT NULL constraint."""

    async def scenario() -> None:
        async with engine.begin() as conn:
            with pytest.raises(IntegrityError):
                await conn.execute(table.insert().values(**row_without_tenant_id))

    run_async(scenario())

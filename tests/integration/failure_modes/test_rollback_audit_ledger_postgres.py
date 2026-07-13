"""Rollback verification gate (testing-strategy.md sec F-7), REAL Postgres
half: "audit verifiable" / "audit-chain preservation" / "tenant isolation
on rollback" against `saena_domain.persistence.postgres.adapters.
PostgresAuditLedger` (real SQL, real `postgres:16-alpine` testcontainer —
not the in-memory reference `tests/security/test_rollback_audit_and_
approval_ledger_immutability.py` already covers).
"""

from __future__ import annotations

import pytest
from failure_modes_postgres_factories import (
    PATCH_UNIT_ID,
    TENANT_A,
    TENANT_B,
    TenantId,
    make_executed_patch_unit_audit_entry,
    make_refused_patch_unit_audit_entry,
    run_async,
)
from saena_domain.persistence.postgres.adapters import PostgresAuditLedger
from saena_domain.persistence.postgres.tables import audit_entries
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


def test_audit_chain_for_a_rolled_back_run_is_persisted_and_verifiable_in_real_postgres(
    engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)

        refused = make_refused_patch_unit_audit_entry(tenant_id=TENANT_A)
        appended_refused = await ledger.append(refused)

        # the retry (a fresh worktree, per the runner's own real behavior)
        # then succeeds — its own audit entry chains onto the refusal.
        retried = make_executed_patch_unit_audit_entry(
            tenant_id=TENANT_A, prev_hash=appended_refused.event_hash.root
        )
        await ledger.append(retried)

        entries = await ledger.read_range(tenant_id=TenantId(TENANT_A))
        assert len(entries) == 2
        assert entries[0].payload["decision"] == "denied_out_of_scope_write"
        assert entries[1].payload["decision"] == "executed"

        ok, bad_index = await ledger.verify(tenant_id=TenantId(TENANT_A))
        assert ok is True
        assert bad_index is None

    run_async(scenario())


def test_a_tampered_row_written_via_raw_sql_is_detected_by_verify(engine: AsyncEngine) -> None:
    """Proves `verify()` inspects COMMITTED row content, not merely
    in-process state — an attacker who could reach the database directly
    (bypassing the append-only `PostgresAuditLedger.append` API entirely)
    and rewrite a rolled-back patch unit's audit row to read "executed" is
    still caught."""

    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        entry = make_refused_patch_unit_audit_entry(tenant_id=TENANT_A)
        await ledger.append(entry)

        async with engine.begin() as conn:
            await conn.execute(
                update(audit_entries)
                .where(audit_entries.c.event_hash == entry.event_hash.root)
                .values(payload={"patch_unit_id": PATCH_UNIT_ID, "decision": "executed"})
            )

        ok, bad_index = await ledger.verify(tenant_id=TenantId(TENANT_A))
        assert ok is False
        assert bad_index == 0

    run_async(scenario())


def test_tenant_b_audit_chain_is_unaffected_by_tenant_a_rollback(engine: AsyncEngine) -> None:
    """ "tenant isolation on rollback" against real Postgres: tenant A's
    refusal is recorded in tenant A's OWN chain only — tenant B's chain
    stays empty/untouched, and each chain verifies independently."""

    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        await ledger.append(make_refused_patch_unit_audit_entry(tenant_id=TENANT_A))
        await ledger.append(make_executed_patch_unit_audit_entry(tenant_id=TENANT_B))

        tenant_a_entries = await ledger.read_range(tenant_id=TenantId(TENANT_A))
        tenant_b_entries = await ledger.read_range(tenant_id=TenantId(TENANT_B))

        assert len(tenant_a_entries) == 1
        assert tenant_a_entries[0].payload["decision"] == "denied_out_of_scope_write"
        assert len(tenant_b_entries) == 1
        assert tenant_b_entries[0].payload["decision"] == "executed"

        ok_a, _ = await ledger.verify(tenant_id=TenantId(TENANT_A))
        ok_b, _ = await ledger.verify(tenant_id=TenantId(TENANT_B))
        assert ok_a is True
        assert ok_b is True

    run_async(scenario())

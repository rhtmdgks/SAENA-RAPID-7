"""Integration tests for `PostgresAuditLedger` — mirrors
`InMemoryAuditLedger`'s reference semantics
(`tests/unit/domain_persistence/test_audit_ledger.py`) over real SQL,
including a genuine UPDATE-via-raw-SQL tamper simulation (the whole point of
proving `verify()` actually inspects committed row content, not merely
replays in-process state)."""

from __future__ import annotations

import pytest
from postgres_factories import make_audit_entry, run_async
from saena_domain.audit import ForbiddenAuditDataError
from saena_domain.audit.chain import AuditEntry
from saena_domain.audit.hashing import compute_entry_hash
from saena_domain.identity import TenantId
from saena_domain.persistence.postgres.adapters import PostgresAuditLedger
from saena_domain.persistence.postgres.tables import audit_entries
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

TENANT_A = TenantId("acme-co")
TENANT_B = TenantId("globex-co")


def test_append_then_read_range_round_trips(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        entry = make_audit_entry()

        await ledger.append(entry)
        read_back = await ledger.read_range(tenant_id=TENANT_A)

        assert read_back == (entry,)

    run_async(scenario())


def test_caller_injected_connection_used_for_append_and_read_range(engine: AsyncEngine) -> None:
    """`append`/`read_range`/`verify` also accept a caller-supplied
    `connection=` (session-scoped variant, `adapters.py`'s module
    docstring)."""

    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        entry = make_audit_entry()

        async with engine.begin() as conn:
            appended = await ledger.append(entry, connection=conn)
            read_back = await ledger.read_range(tenant_id=TENANT_A, connection=conn)
            ok, index = await ledger.verify(tenant_id=TENANT_A, connection=conn)

        assert appended == entry
        assert read_back == (entry,)
        assert ok is True
        assert index is None

    run_async(scenario())


def test_chain_verifies_after_appends(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        first = make_audit_entry()
        await ledger.append(first)
        second = make_audit_entry(prev_hash=first.event_hash, payload={"patch_unit_id": "next"})
        await ledger.append(second)

        ok, index = await ledger.verify(tenant_id=TENANT_A)

        assert ok is True
        assert index is None

    run_async(scenario())


def test_append_rejects_entry_that_does_not_link_to_tail(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        await ledger.append(make_audit_entry())
        stray = make_audit_entry(payload={"patch_unit_id": "stray"})

        with pytest.raises(ValueError, match="prev_event_hash"):
            await ledger.append(stray)

    run_async(scenario())


def test_system_scope_and_tenant_scope_chains_are_independent(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        tenant_entry = make_audit_entry()
        system_entry = make_audit_entry(
            scope="system", tenant_id=None, run_id=None, payload={"patch_unit_id": "sys"}
        )

        await ledger.append(tenant_entry)
        await ledger.append(system_entry)

        assert await ledger.read_range(tenant_id=TENANT_A) == (tenant_entry,)
        assert await ledger.read_range(tenant_id=None) == (system_entry,)

    run_async(scenario())


def test_cross_tenant_chains_never_mixed(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        entry_a = make_audit_entry(tenant_id="acme-co")
        entry_b = make_audit_entry(tenant_id="globex-co", run_id="run-b")

        await ledger.append(entry_a)
        await ledger.append(entry_b)

        range_a = await ledger.read_range(tenant_id=TENANT_A)
        range_b = await ledger.read_range(tenant_id=TENANT_B)
        assert range_a == (entry_a,)
        assert range_b == (entry_b,)
        assert entry_b not in range_a
        assert entry_a not in range_b

    run_async(scenario())


def test_append_rejects_forbidden_payload(engine: AsyncEngine) -> None:
    with pytest.raises(ForbiddenAuditDataError):
        make_audit_entry(payload={"password": "hunter2"})


def test_read_range_start_end_index_slices(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        first = make_audit_entry()
        await ledger.append(first)
        second = make_audit_entry(prev_hash=first.event_hash, payload={"patch_unit_id": "second"})
        await ledger.append(second)
        third = make_audit_entry(prev_hash=second.event_hash, payload={"patch_unit_id": "third"})
        await ledger.append(third)

        sliced = await ledger.read_range(tenant_id=TENANT_A, start_index=1, end_index=2)

        assert sliced == (second,)

    run_async(scenario())


def test_tampering_via_raw_sql_update_is_detected_by_verify(engine: AsyncEngine) -> None:
    """The whole point of this integration test: mutate a COMMITTED row via
    raw SQL (bypassing the adapter entirely, exactly what a rogue direct-DB
    access or a bug elsewhere in the stack might do) and prove `verify()`
    still catches it by re-reading and re-hashing real persisted content —
    not by trusting any in-process cache."""

    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        entry = await ledger.append(make_audit_entry())

        async with engine.begin() as conn:
            await conn.execute(
                audit_entries.update()
                .where(
                    audit_entries.c.scope_key == "acme-co",
                    audit_entries.c.event_hash == entry.event_hash.root,
                )
                .values(payload={"patch_unit_id": "TAMPERED"})
            )

        ok, index = await ledger.verify(tenant_id=TENANT_A)

        assert ok is False
        assert index == 0

    run_async(scenario())


def test_tampering_prev_event_hash_via_raw_sql_is_detected_by_verify(engine: AsyncEngine) -> None:
    """Distinct tamper shape from the payload-content test above: mutate the
    STORED `prev_event_hash` link directly (rather than the hashed content),
    proving `verify()`'s prev-link mismatch branch — not just its
    recomputed-content-hash mismatch branch — is independently exercised."""

    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        first = await ledger.append(make_audit_entry())
        second = await ledger.append(
            make_audit_entry(prev_hash=first.event_hash, payload={"patch_unit_id": "second"})
        )

        async with engine.begin() as conn:
            await conn.execute(
                audit_entries.update()
                .where(
                    audit_entries.c.scope_key == "acme-co",
                    audit_entries.c.event_hash == second.event_hash.root,
                )
                .values(prev_event_hash="sha256:" + "0" * 64)
            )

        ok, index = await ledger.verify(tenant_id=TENANT_A)

        assert ok is False
        assert index == 1

    run_async(scenario())


def test_append_rejects_entry_whose_event_hash_does_not_match_its_own_content(
    engine: AsyncEngine,
) -> None:
    """`append`'s own self-hash check (distinct from the prev-link check
    `test_append_rejects_entry_that_does_not_link_to_tail` exercises): an
    entry whose `prev_event_hash` correctly targets the current tail but
    whose `event_hash` does NOT match its own recomputed content is
    rejected before ever reaching storage."""

    async def scenario() -> None:
        ledger = PostgresAuditLedger(engine)
        genuine = make_audit_entry()
        tampered = AuditEntry.model_validate(
            {
                **genuine.model_dump(mode="json"),
                "event_hash": "sha256:" + "f" * 64,
            }
        )

        with pytest.raises(ValueError, match="event_hash"):
            await ledger.append(tampered)

    run_async(scenario())


def test_append_guard_invoked_even_on_pre_built_entry_with_forbidden_payload(
    engine: AsyncEngine,
) -> None:
    """Belt-and-suspenders parity with `InMemoryAuditLedger`: `append` itself
    re-runs `guard_payload`, constructing the underlying generated model
    directly to bypass `build_entry`'s own guard (same technique the
    in-memory reference test uses)."""

    async def scenario() -> None:
        fields_for_hash = {
            "action": "patch.unit.completed.v1",
            "recorded_at": "2026-07-13T09:14:32Z",
            "scope": "tenant",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "payload": {"password": "hunter2"},
            "tenant_id": "acme-co",
            "run_id": "run-2026-0713-0013",
        }
        event_hash = compute_entry_hash(fields_for_hash, None)
        entry = AuditEntry.model_validate(
            {"event_hash": event_hash, "prev_event_hash": None, **fields_for_hash}
        )

        ledger = PostgresAuditLedger(engine)
        with pytest.raises(ForbiddenAuditDataError):
            await ledger.append(entry)

    run_async(scenario())

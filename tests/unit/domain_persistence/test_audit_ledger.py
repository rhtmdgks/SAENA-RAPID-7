"""Tests for `InMemoryAuditLedger` (`AuditLedgerPort` port).

Covers: append-only invariant (no public mutation API), hash-chain
continuity, tenant isolation (per-tenant chains never mixed), tamper
simulation (verify() detects tampering via direct private-attribute access —
the only way to mutate a chain entry, proving the class itself exposes no
such capability), and forbidden-data rejection on append.
"""

from __future__ import annotations

import pytest
from persistence_factories import make_audit_entry
from saena_domain.audit import ForbiddenAuditDataError
from saena_domain.audit.chain import AuditEntry
from saena_domain.audit.hashing import compute_entry_hash
from saena_domain.identity import TenantId
from saena_domain.persistence import InMemoryAuditLedger

TENANT_A = TenantId("acme-co")
TENANT_B = TenantId("globex-co")


def test_append_then_read_range_round_trips() -> None:
    ledger = InMemoryAuditLedger()
    entry = make_audit_entry()

    ledger.append(entry)

    assert ledger.read_range(tenant_id=TENANT_A) == (entry,)


def test_chain_verifies_after_appends() -> None:
    ledger = InMemoryAuditLedger()
    first = make_audit_entry()
    ledger.append(first)
    second = make_audit_entry(prev_hash=first.event_hash, payload={"patch_unit_id": "next"})
    ledger.append(second)

    ok, index = ledger.verify(tenant_id=TENANT_A)

    assert ok is True
    assert index is None


def test_append_rejects_entry_that_does_not_link_to_tail() -> None:
    ledger = InMemoryAuditLedger()
    ledger.append(make_audit_entry())
    # A second GENESIS-rooted entry does not extend the existing tail.
    stray = make_audit_entry(payload={"patch_unit_id": "stray"})

    with pytest.raises(ValueError, match="prev_event_hash"):
        ledger.append(stray)


def test_system_scope_and_tenant_scope_chains_are_independent() -> None:
    ledger = InMemoryAuditLedger()
    tenant_entry = make_audit_entry()
    system_entry = make_audit_entry(
        scope="system", tenant_id=None, run_id=None, payload={"patch_unit_id": "sys"}
    )

    ledger.append(tenant_entry)
    ledger.append(system_entry)

    assert ledger.read_range(tenant_id=TENANT_A) == (tenant_entry,)
    assert ledger.read_range(tenant_id=None) == (system_entry,)


def test_cross_tenant_chains_never_mixed() -> None:
    ledger = InMemoryAuditLedger()
    entry_a = make_audit_entry(tenant_id="acme-co")
    entry_b = make_audit_entry(tenant_id="globex-co", run_id="run-b")

    ledger.append(entry_a)
    ledger.append(entry_b)

    assert ledger.read_range(tenant_id=TENANT_A) == (entry_a,)
    assert ledger.read_range(tenant_id=TENANT_B) == (entry_b,)
    # Reading tenant A never returns tenant B's entry and vice versa.
    assert entry_b not in ledger.read_range(tenant_id=TENANT_A)
    assert entry_a not in ledger.read_range(tenant_id=TENANT_B)


def test_no_public_mutation_api_exists() -> None:
    """Append-only by interface shape: the class exposes append/read_range/
    verify only — no update/delete/remove/clear method."""
    public_methods = {
        name
        for name in dir(InMemoryAuditLedger)
        if not name.startswith("_") and callable(getattr(InMemoryAuditLedger, name))
    }
    assert public_methods == {"append", "read_range", "verify"}


def test_tampering_simulation_is_detected_by_verify() -> None:
    """Direct private-attribute access is the ONLY way to tamper — proving
    verify() is not trivially always-green."""
    ledger = InMemoryAuditLedger()
    entry = make_audit_entry()
    ledger.append(entry)

    # AuditEntry is a frozen pydantic model — build a tampered copy via
    # model_copy(update=...) and splice it into the private chain list
    # directly (white-box test, see memory.py's "test-only tamper
    # simulation" comment).
    tampered = entry.model_copy(update={"payload": {"patch_unit_id": "tampered"}})
    ledger._tenant_chains[TENANT_A.value][0] = tampered  # noqa: SLF001

    ok, index = ledger.verify(tenant_id=TENANT_A)

    assert ok is False
    assert index == 0


def test_append_rejects_forbidden_payload() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        make_audit_entry(payload={"password": "hunter2"})


def test_append_guard_invoked_even_on_pre_built_entry_with_forbidden_payload() -> None:
    """guard_payload runs again at append() time (not just build_entry time)
    — belt-and-suspenders so the port never trusts a caller-constructed
    AuditEntry without re-checking.

    Bypasses `build_entry`'s own guard by constructing the generated model
    directly with a forbidden-shaped payload key, then wrapping it as an
    `AuditEntry` via `model_validate` (same technique `chain.py`'s
    `build_entry` uses internally) to prove `InMemoryAuditLedger.append` is
    itself a guard choke point, not merely relying on `build_entry` having
    already run.
    """
    fields_for_hash = {
        "action": "patch.unit.completed.v1",
        "recorded_at": "2026-07-12T09:14:32Z",
        "scope": "tenant",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "payload": {"password": "hunter2"},
        "tenant_id": "acme-co",
        "run_id": "run-2026-0712-0007",
    }
    event_hash = compute_entry_hash(fields_for_hash, None)
    entry = AuditEntry.model_validate(
        {
            "event_hash": event_hash,
            "prev_event_hash": None,
            **fields_for_hash,
        }
    )

    ledger = InMemoryAuditLedger()
    with pytest.raises(ForbiddenAuditDataError):
        ledger.append(entry)

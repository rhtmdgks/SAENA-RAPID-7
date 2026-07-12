"""Tests for saena_domain.audit.chain — entry model, builder, verify, tamper detection."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError
from saena_domain.audit.chain import (
    AuditEntry,
    InMemoryAuditChain,
    append_entry,
    build_entry,
    verify_chain,
)
from saena_domain.audit.guard import ForbiddenAuditDataError
from saena_domain.audit.hashing import GENESIS

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def _entry_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "action": "patch.unit.completed.v1",
        "recorded_at": "2026-07-12T09:14:32Z",
        "scope": "tenant",
        "trace_id": TRACE_ID,
        "payload": {"patch_unit_id": "w2-04-audit"},
        "tenant_id": "acme-co",
        "run_id": "run-2026-0712-0007",
    }
    base.update(overrides)
    return base


# --- genesis semantics -----------------------------------------------------------


def test_genesis_first_entry_has_none_prev_hash() -> None:
    entry = build_entry(prev_hash=GENESIS, **_entry_kwargs())
    assert entry.prev_event_hash is None


def test_in_memory_chain_starts_empty_with_genesis_tail() -> None:
    chain = InMemoryAuditChain()
    assert chain.entries == ()
    assert chain.tail_hash is GENESIS


def test_in_memory_chain_first_append_links_to_genesis() -> None:
    chain = InMemoryAuditChain()
    entry = chain.append(**_entry_kwargs())
    assert entry.prev_event_hash is None


# --- scope / tenant_id / run_id conditional rules (R9-1 mirror) --------------------


def test_tenant_scope_requires_tenant_id() -> None:
    with pytest.raises(ValidationError):
        AuditEntry(
            event_hash="sha256:" + "a" * 64,
            prev_event_hash=None,
            action="patch.unit.completed.v1",
            recorded_at="2026-07-12T09:14:32Z",
            scope="tenant",
            trace_id=TRACE_ID,
            payload={},
        )


def test_system_scope_forbids_tenant_id() -> None:
    with pytest.raises(ValidationError):
        AuditEntry(
            event_hash="sha256:" + "a" * 64,
            prev_event_hash=None,
            action="adapter.config.updated.v1",
            recorded_at="2026-07-12T09:14:32Z",
            scope="system",
            trace_id=TRACE_ID,
            payload={},
            tenant_id="acme-co",
        )


def test_system_scope_forbids_run_id() -> None:
    with pytest.raises(ValidationError):
        AuditEntry(
            event_hash="sha256:" + "a" * 64,
            prev_event_hash=None,
            action="adapter.config.updated.v1",
            recorded_at="2026-07-12T09:14:32Z",
            scope="system",
            trace_id=TRACE_ID,
            payload={},
            run_id="run-1",
        )


def test_system_scope_valid_without_tenant_or_run() -> None:
    entry = AuditEntry(
        event_hash="sha256:" + "a" * 64,
        prev_event_hash=None,
        action="adapter.config.updated.v1",
        recorded_at="2026-07-12T09:14:32Z",
        scope="system",
        trace_id=TRACE_ID,
        payload={},
    )
    assert entry.tenant_id is None
    assert entry.run_id is None


# --- guard integration on build ----------------------------------------------------


def test_build_entry_rejects_forbidden_payload() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        build_entry(prev_hash=GENESIS, **_entry_kwargs(payload={"password": "hunter2"}))


def test_build_entry_minimizes_actor_to_actor_id() -> None:
    entry = build_entry(
        prev_hash=GENESIS,
        **_entry_kwargs(actor={"actor_id": "user-123"}),
    )
    assert entry.actor_id == "user-123"


def test_build_entry_rejects_actor_with_extra_fields() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        build_entry(
            prev_hash=GENESIS,
            **_entry_kwargs(actor={"actor_id": "user-123", "email": "user@example.com"}),
        )


# --- error-detail pass-through (error_code only, ADR-0015) -------------------------


def test_build_entry_accepts_error_code_matching_taxonomy_pattern() -> None:
    entry = build_entry(
        prev_hash=GENESIS,
        **_entry_kwargs(error_code="saena.internal.unexpected"),
    )
    assert entry.error_code == "saena.internal.unexpected"


def test_audit_entry_rejects_malformed_error_code() -> None:
    with pytest.raises(ValidationError):
        AuditEntry(
            event_hash="sha256:" + "a" * 64,
            prev_event_hash=None,
            action="patch.unit.completed.v1",
            recorded_at="2026-07-12T09:14:32Z",
            scope="system",
            trace_id=TRACE_ID,
            payload={},
            error_code="NOT-A-VALID-CODE",
        )


# --- append_entry + verify_chain determinism ---------------------------------------


def test_append_entry_returns_new_list_without_mutating_input() -> None:
    chain: list[AuditEntry] = []
    entry = build_entry(prev_hash=GENESIS, **_entry_kwargs())
    new_chain = append_entry(chain, entry)
    assert chain == []
    assert new_chain == [entry]


def test_append_entry_rejects_mismatched_prev_hash() -> None:
    entry = build_entry(prev_hash="sha256:" + "9" * 64, **_entry_kwargs())
    with pytest.raises(ValueError, match="prev_event_hash"):
        append_entry([], entry)


def test_append_entry_rejects_self_inconsistent_event_hash() -> None:
    entry = build_entry(prev_hash=GENESIS, **_entry_kwargs())
    data = entry.model_dump(mode="json")
    data["event_hash"] = "sha256:" + "7" * 64
    tampered = AuditEntry.model_construct(**data)
    with pytest.raises(ValueError, match="event_hash does not match"):
        append_entry([], tampered)


def test_verify_chain_empty_is_valid() -> None:
    assert verify_chain([]) == (True, None)


def test_verify_chain_single_entry_valid() -> None:
    entry = build_entry(prev_hash=GENESIS, **_entry_kwargs())
    assert verify_chain([entry]) == (True, None)


def test_verify_chain_multi_entry_valid() -> None:
    chain = InMemoryAuditChain()
    chain.append(**_entry_kwargs())
    chain.append(**_entry_kwargs(recorded_at="2026-07-12T09:15:00Z"))
    chain.append(**_entry_kwargs(recorded_at="2026-07-12T09:16:00Z"))
    assert verify_chain(list(chain.entries)) == (True, None)


def test_chain_hash_is_deterministic_given_same_inputs() -> None:
    entry_a = build_entry(prev_hash=GENESIS, **_entry_kwargs())
    entry_b = build_entry(prev_hash=GENESIS, **_entry_kwargs())
    assert entry_a.event_hash == entry_b.event_hash


# --- tamper detection: head / middle / tail ----------------------------------------


def _build_three_entry_chain() -> list[AuditEntry]:
    chain = InMemoryAuditChain()
    chain.append(**_entry_kwargs(payload={"seq": 0}))
    chain.append(**_entry_kwargs(payload={"seq": 1}, recorded_at="2026-07-12T09:15:00Z"))
    chain.append(**_entry_kwargs(payload={"seq": 2}, recorded_at="2026-07-12T09:16:00Z"))
    return list(chain.entries)


def _tamper_payload(entry: AuditEntry, new_payload: dict[str, object]) -> AuditEntry:
    data = entry.model_dump(mode="json")
    data["payload"] = new_payload
    return AuditEntry.model_construct(**{**data, "payload": new_payload})


def test_tamper_at_head_detected() -> None:
    entries = _build_three_entry_chain()
    entries[0] = _tamper_payload(entries[0], {"seq": "TAMPERED"})
    ok, index = verify_chain(entries)
    assert ok is False
    assert index == 0


def test_tamper_at_middle_detected() -> None:
    entries = _build_three_entry_chain()
    entries[1] = _tamper_payload(entries[1], {"seq": "TAMPERED"})
    ok, index = verify_chain(entries)
    assert ok is False
    assert index == 1


def test_tamper_at_tail_detected() -> None:
    entries = _build_three_entry_chain()
    entries[2] = _tamper_payload(entries[2], {"seq": "TAMPERED"})
    ok, index = verify_chain(entries)
    assert ok is False
    assert index == 2


def test_tamper_event_hash_directly_breaks_next_link() -> None:
    entries = _build_three_entry_chain()
    data = entries[0].model_dump(mode="json")
    data["event_hash"] = "sha256:" + "f" * 64
    entries[0] = AuditEntry.model_construct(**data)
    ok, index = verify_chain(entries)
    assert ok is False
    # entries[0] itself no longer self-verifies against its own recomputed
    # hash (its stored event_hash was overwritten), so index 0 is reported.
    assert index == 0


def test_tamper_prev_event_hash_directly_breaks_own_link() -> None:
    entries = _build_three_entry_chain()
    data = entries[1].model_dump(mode="json")
    data["prev_event_hash"] = "sha256:" + "e" * 64
    entries[1] = AuditEntry.model_construct(**data)
    ok, index = verify_chain(entries)
    assert ok is False
    assert index == 1


def test_reordering_entries_detected_as_tamper() -> None:
    entries = _build_three_entry_chain()
    reordered = [entries[0], entries[2], entries[1]]
    ok, index = verify_chain(reordered)
    assert ok is False
    assert index == 1


def test_deep_copy_of_valid_chain_still_verifies() -> None:
    entries = _build_three_entry_chain()
    duplicate = copy.deepcopy(entries)
    assert verify_chain(duplicate) == (True, None)


# --- InMemoryAuditChain integration -------------------------------------------------


def test_in_memory_chain_append_and_verify_round_trip() -> None:
    chain = InMemoryAuditChain()
    for i in range(5):
        chain.append(**_entry_kwargs(payload={"seq": i}, recorded_at=f"2026-07-12T09:{14 + i}:00Z"))
    assert len(chain.entries) == 5
    assert chain.verify() == (True, None)


def test_in_memory_chain_entries_is_read_only_tuple() -> None:
    chain = InMemoryAuditChain()
    chain.append(**_entry_kwargs())
    assert isinstance(chain.entries, tuple)

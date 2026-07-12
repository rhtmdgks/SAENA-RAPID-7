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
from saena_schemas.domain.audit_event_v1 import AuditEvent, Sha256Ref

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


# --- inherited generated-model constraints (critic MUST-FIX regression) ------------
#
# AuditEntry SUBCLASSES saena_schemas.domain.audit_event_v1.AuditEvent rather
# than hand-declaring fields — these tests pin that the generated model's
# tenant_id/run_id/actor_id constraints (TenantId/RunId/ActorId root-model
# patterns and length bounds from common/identifiers/v1) are enforced on
# AuditEntry, not silently dropped by a weaker hand-copied `str | None`.


def _tenant_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "event_hash": "sha256:" + "a" * 64,
        "prev_event_hash": None,
        "action": "patch.unit.completed.v1",
        "recorded_at": "2026-07-12T09:14:32Z",
        "scope": "tenant",
        "trace_id": TRACE_ID,
        "payload": {},
        "tenant_id": "acme-co",
    }
    base.update(overrides)
    return base


def test_tenant_id_rejects_uppercase() -> None:
    # TenantId pattern is ^[a-z0-9]([a-z0-9-]{1,30}[a-z0-9])$ — lowercase
    # only (ADR-0014). A hand-copied bare `str` field would have accepted
    # this; the inherited TenantId root-model must not.
    with pytest.raises(ValidationError):
        AuditEntry(**_tenant_kwargs(tenant_id="ACME-CO"))


def test_tenant_id_rejects_over_32_chars() -> None:
    with pytest.raises(ValidationError):
        AuditEntry(**_tenant_kwargs(tenant_id="a" + "b" * 31 + "a"))


def test_tenant_id_rejects_empty_string() -> None:
    with pytest.raises(ValidationError):
        AuditEntry(**_tenant_kwargs(tenant_id=""))


def test_tenant_id_accepts_valid_slug() -> None:
    entry = AuditEntry(**_tenant_kwargs(tenant_id="acme-co"))
    assert entry.tenant_id is not None
    assert entry.tenant_id.root == "acme-co"


def test_run_id_rejects_over_128_chars() -> None:
    with pytest.raises(ValidationError):
        AuditEntry(**_tenant_kwargs(run_id="r" * 129))


def test_run_id_rejects_empty_string() -> None:
    with pytest.raises(ValidationError):
        AuditEntry(**_tenant_kwargs(run_id=""))


def test_run_id_accepts_valid_value() -> None:
    entry = AuditEntry(**_tenant_kwargs(run_id="run-2026-0712-0007"))
    assert entry.run_id is not None
    assert entry.run_id.root == "run-2026-0712-0007"


def test_actor_id_rejects_over_128_chars() -> None:
    with pytest.raises(ValidationError):
        AuditEntry(**_tenant_kwargs(actor_id="u" * 129))


def test_actor_id_rejects_empty_string() -> None:
    with pytest.raises(ValidationError):
        AuditEntry(**_tenant_kwargs(actor_id=""))


def test_actor_id_accepts_valid_value() -> None:
    entry = AuditEntry(**_tenant_kwargs(actor_id="user-123"))
    assert entry.actor_id is not None
    assert entry.actor_id.root == "user-123"


def test_audit_entry_is_subclass_of_generated_audit_event() -> None:
    # Pins the inheritance relationship itself — if a future edit reverts to
    # hand-declared fields, this fails immediately rather than only failing
    # on the more indirect constraint-drift tests above.
    assert issubclass(AuditEntry, AuditEvent)


# --- guard integration on build ----------------------------------------------------


def test_build_entry_rejects_forbidden_payload() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        build_entry(prev_hash=GENESIS, **_entry_kwargs(payload={"password": "hunter2"}))


def test_build_entry_minimizes_actor_to_actor_id() -> None:
    entry = build_entry(
        prev_hash=GENESIS,
        **_entry_kwargs(actor={"actor_id": "user-123"}),
    )
    # actor_id is inherited from the generated AuditEvent model as ActorId
    # (a pydantic RootModel[str], NOT a bare str) — compare via .root.
    assert entry.actor_id is not None
    assert entry.actor_id.root == "user-123"


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
    # dict(entry) preserves the actual field values (Sha256Ref/TenantId/...
    # root-model instances, TimestampUtc, Scope enum), unlike
    # model_dump(mode="json") which unwraps everything to plain
    # JSON-serializable values — model_construct bypasses validation, so
    # feeding it plain strings for root-model fields would silently store
    # the wrong runtime type (only the ONE field under test should be
    # deliberately mistyped/mismatched, simulating direct storage tampering).
    data = dict(entry)
    data["event_hash"] = Sha256Ref("sha256:" + "7" * 64)
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
    data = dict(entry)
    data["payload"] = new_payload
    return AuditEntry.model_construct(**data)


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
    data = dict(entries[0])
    data["event_hash"] = Sha256Ref("sha256:" + "f" * 64)
    entries[0] = AuditEntry.model_construct(**data)
    ok, index = verify_chain(entries)
    assert ok is False
    # entries[0] itself no longer self-verifies against its own recomputed
    # hash (its stored event_hash was overwritten), so index 0 is reported.
    assert index == 0


def test_tamper_prev_event_hash_directly_breaks_own_link() -> None:
    entries = _build_three_entry_chain()
    data = dict(entries[1])
    data["prev_event_hash"] = Sha256Ref("sha256:" + "e" * 64)
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

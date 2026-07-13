"""Tests for `InMemoryOutbox` (`OutboxPort` port) — W2A "recording only" scope."""

from __future__ import annotations

import pytest
from persistence_factories import make_system_envelope, make_tenant_envelope
from saena_domain.audit import ForbiddenAuditDataError
from saena_domain.identity import TenantId
from saena_domain.persistence import (
    InMemoryOutbox,
    NotFoundError,
    OutboxValidationError,
    TenantIsolationError,
)

TENANT_A = TenantId("acme-co")
TENANT_B = TenantId("globex-co")


def test_record_then_list_pending_round_trips() -> None:
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()

    stored = outbox.record(envelope)

    assert stored == envelope
    assert outbox.list_pending(TENANT_A) == (envelope,)


def test_record_rejects_invalid_envelope_shape() -> None:
    outbox = InMemoryOutbox()

    with pytest.raises(OutboxValidationError):
        outbox.record({"not": "an envelope"})


def test_record_rejects_envelope_missing_required_field() -> None:
    """`event_type` itself is an open string at the generic envelope-schema
    level (the closed-catalog check is `EnvelopeFactory`-only, ADR-0013
    "AsyncAPI 토픽 1:1" enforcement, not part of the envelope contract
    `record` re-validates against) — so a missing REQUIRED field
    (`trace_id`) is what proves `record`'s own dual validation actually
    runs, rather than a structurally-shaped-but-unknown event_type."""
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()
    del envelope["trace_id"]

    with pytest.raises(OutboxValidationError):
        outbox.record(envelope)


def test_record_dedups_identical_envelope_by_event_id() -> None:
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()

    first = outbox.record(envelope)
    second = outbox.record(dict(envelope))

    assert first == second
    assert len(outbox.list_pending(TENANT_A)) == 1


def test_record_rejects_same_event_id_different_content() -> None:
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()
    outbox.record(envelope)
    conflicting = dict(envelope)
    conflicting["idempotency_key"] = "different-key"

    with pytest.raises(OutboxValidationError):
        outbox.record(conflicting)


def test_mark_published_removes_from_pending() -> None:
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()
    outbox.record(envelope)

    outbox.mark_published(TENANT_A, envelope["event_id"])

    assert outbox.list_pending(TENANT_A) == ()


def test_mark_published_missing_event_id_raises_not_found() -> None:
    outbox = InMemoryOutbox()

    with pytest.raises(NotFoundError):
        outbox.mark_published(TENANT_A, "nonexistent-event-id")


def test_mark_published_cross_tenant_denied_direction_a_to_b() -> None:
    """Tenant B must not be able to mark tenant A's event published."""
    outbox = InMemoryOutbox()
    envelope_a = make_tenant_envelope(tenant_id="acme-co", run_id="run-a")
    outbox.record(envelope_a)

    with pytest.raises(TenantIsolationError):
        outbox.mark_published(TENANT_B, envelope_a["event_id"])

    # The event remains unpublished — the denied call had no side effect.
    assert outbox.list_pending(TENANT_A) == (envelope_a,)


def test_mark_published_cross_tenant_denied_direction_b_to_a() -> None:
    """Symmetric to the A->B case: tenant A must not mark tenant B's event."""
    outbox = InMemoryOutbox()
    envelope_b = make_tenant_envelope(
        tenant_id="globex-co",
        run_id="run-b",
        idempotency_key="globex-co:run-b:patch-unit-1",
    )
    outbox.record(envelope_b)

    with pytest.raises(TenantIsolationError):
        outbox.mark_published(TENANT_A, envelope_b["event_id"])

    assert outbox.list_pending(TENANT_B) == (envelope_b,)


def test_mark_published_system_envelope_requires_none_tenant_id() -> None:
    """A `context_type: system` envelope's owning scope is `tenant_id=None`
    — passing a real tenant_id against it is denied, `None` succeeds."""
    outbox = InMemoryOutbox()
    envelope = make_system_envelope()
    outbox.record(envelope)

    with pytest.raises(TenantIsolationError):
        outbox.mark_published(TENANT_A, envelope["event_id"])

    outbox.mark_published(None, envelope["event_id"])
    assert outbox.list_pending() == ()


def test_mark_published_tenant_envelope_rejects_none_tenant_id() -> None:
    """The reverse direction: a `context_type: tenant` envelope's owning
    scope is its own tenant_id — passing `None` (system-scope) is denied."""
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()
    outbox.record(envelope)

    with pytest.raises(TenantIsolationError):
        outbox.mark_published(None, envelope["event_id"])


def test_list_pending_filters_by_tenant() -> None:
    outbox = InMemoryOutbox()
    envelope_a = make_tenant_envelope(tenant_id="acme-co", run_id="run-a")
    envelope_b = make_tenant_envelope(
        tenant_id="globex-co",
        run_id="run-b",
        idempotency_key="globex-co:run-b:patch-unit-1",
    )
    outbox.record(envelope_a)
    outbox.record(envelope_b)

    pending_a = outbox.list_pending(TenantId("acme-co"))

    assert pending_a == (envelope_a,)


def test_list_pending_none_returns_every_tenant() -> None:
    outbox = InMemoryOutbox()
    envelope_a = make_tenant_envelope(tenant_id="acme-co", run_id="run-a")
    envelope_b = make_tenant_envelope(
        tenant_id="globex-co",
        run_id="run-b",
        idempotency_key="globex-co:run-b:patch-unit-1",
    )
    outbox.record(envelope_a)
    outbox.record(envelope_b)

    pending = outbox.list_pending()

    assert set(e["event_id"] for e in pending) == {envelope_a["event_id"], envelope_b["event_id"]}


def test_record_rejects_forbidden_data_in_payload() -> None:
    outbox = InMemoryOutbox()
    # `patch.unit.completed.v1`'s bound payload model rejects unknown keys
    # outright (EnvelopeValidationError, before the outbox guard even runs),
    # so this test uses `demand.graph.versioned.v1` — envelope-only, no
    # bound payload model (asyncapi.yaml P1 note) — to exercise the outbox's
    # OWN guard_payload call on an otherwise envelope-schema-valid payload.
    envelope = make_tenant_envelope(
        producer="demand-graph-service",
        event_type="demand.graph.versioned.v1",
        idempotency_key="acme-co:run-2026-0712-0007:demand-graph-v1",
        payload={"password": "hunter2"},
    )

    with pytest.raises(ForbiddenAuditDataError):
        outbox.record(envelope)


def test_record_return_value_mutation_does_not_corrupt_store() -> None:
    """Critic MUST-FIX 2: `record`'s return value must be a deep copy — the
    envelope's nested `payload` dict is where a shallow copy would leak a
    live alias."""
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()

    stored = outbox.record(envelope)
    stored["payload"]["patch_unit_id"] = "TAMPERED"

    pending = outbox.list_pending(TENANT_A)
    assert pending[0]["payload"]["patch_unit_id"] == "w2-07-persistence"


def test_list_pending_return_value_mutation_does_not_corrupt_store() -> None:
    """Critic MUST-FIX 2: `list_pending`'s returned envelopes must be deep
    copies — mutating one must not affect a second `list_pending` call."""
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()
    outbox.record(envelope)

    pending_first = outbox.list_pending(TENANT_A)
    pending_first[0]["payload"]["patch_unit_id"] = "TAMPERED"

    pending_second = outbox.list_pending(TENANT_A)
    assert pending_second[0]["payload"]["patch_unit_id"] == "w2-07-persistence"


def test_record_replay_return_value_mutation_does_not_corrupt_store() -> None:
    """Critic MUST-FIX 2: the identical-replay return path (existing ==
    envelope) must also return a deep copy, not the live stored dict."""
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()
    outbox.record(envelope)

    replay_result = outbox.record(dict(envelope))
    replay_result["payload"]["patch_unit_id"] = "TAMPERED"

    pending = outbox.list_pending(TENANT_A)
    assert pending[0]["payload"]["patch_unit_id"] == "w2-07-persistence"

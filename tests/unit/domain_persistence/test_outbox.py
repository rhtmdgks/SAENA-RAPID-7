"""Tests for `InMemoryOutbox` (`OutboxPort` port) — W2A "recording only" scope."""

from __future__ import annotations

import pytest
from persistence_factories import make_tenant_envelope
from saena_domain.audit import ForbiddenAuditDataError
from saena_domain.identity import TenantId
from saena_domain.persistence import InMemoryOutbox, NotFoundError, OutboxValidationError

TENANT_A = TenantId("acme-co")


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

    outbox.mark_published(envelope["event_id"])

    assert outbox.list_pending(TENANT_A) == ()


def test_mark_published_missing_event_id_raises_not_found() -> None:
    outbox = InMemoryOutbox()

    with pytest.raises(NotFoundError):
        outbox.mark_published("nonexistent-event-id")


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

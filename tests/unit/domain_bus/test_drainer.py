"""Tests for `saena_domain.bus.drainer.OutboxDrainer` — InMemoryOutbox + InMemoryPublisher."""

from __future__ import annotations

import asyncio

from bus_factories import (
    AlwaysFailsPublisher,
    AsyncFailingDLQPublisher,
    AsyncOutboxWrapper,
    FailNTimesPublisher,
    make_aggregate_envelope,
    make_pending_review_aggregate_envelope,
    make_suppressed_aggregate_envelope,
    make_system_envelope,
    make_tenant_envelope,
)
from saena_domain.bus.drainer import OutboxDrainer
from saena_domain.bus.publisher import InMemoryPublisher, dlq_topic_for
from saena_domain.identity import TenantId
from saena_domain.persistence import InMemoryOutbox

TENANT_A = TenantId("acme-co")


def test_happy_drain_publishes_and_marks_published() -> None:
    outbox = InMemoryOutbox()
    publisher = InMemoryPublisher()
    envelope = make_tenant_envelope()
    outbox.record(envelope)
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.published == (envelope["event_id"],)
    assert result.dead_lettered == ()
    assert result.suppressed == ()
    assert result.retried_pending == ()
    assert publisher.published == ((envelope["event_type"], envelope),)
    assert outbox.list_pending() == ()


def test_async_outbox_port_drains_correctly() -> None:
    """`OutboxDrainer` must work transparently against an ASYNC-shaped
    `OutboxPort` (`PostgresOutbox`-shaped `list_pending`/`mark_published`
    coroutines, not `InMemoryOutbox`'s plain sync methods) — exercises
    `_maybe_await`'s awaitable branch directly, proving it is not only
    reachable via the real-Postgres integration suite."""
    inner = InMemoryOutbox()
    envelope = make_tenant_envelope()
    inner.record(envelope)
    outbox = AsyncOutboxWrapper(inner)
    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.published == (envelope["event_id"],)
    assert publisher.published == ((envelope["event_type"], envelope),)
    # The mark_published call genuinely landed on the wrapped inner outbox —
    # only observable if the coroutine actually ran to completion.
    assert inner.list_pending() == ()


def test_publish_failure_leaves_row_pending_not_marked() -> None:
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()
    outbox.record(envelope)
    drainer = OutboxDrainer(outbox, AlwaysFailsPublisher())

    result = asyncio.run(drainer.drain_once())

    assert result.published == ()
    assert result.retried_pending == (envelope["event_id"],)
    # NEVER marked published on failure — still pending for the next drain.
    assert outbox.list_pending() == (envelope,)


def test_publish_failure_then_success_on_retry() -> None:
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()
    outbox.record(envelope)
    publisher = FailNTimesPublisher(fail_count=1)
    drainer = OutboxDrainer(outbox, publisher)

    first = asyncio.run(drainer.drain_once())
    assert first.retried_pending == (envelope["event_id"],)
    assert outbox.list_pending() == (envelope,)

    second = asyncio.run(drainer.drain_once())
    assert second.published == (envelope["event_id"],)
    assert outbox.list_pending() == ()
    assert publisher.published == [(envelope["event_type"], envelope)]


def test_malformed_envelope_routes_to_dlq_not_main_topic() -> None:
    """A structurally-invalid envelope smuggled into the outbox (defense in
    depth — `OutboxPort.record` should already have rejected it, but the
    drainer must not trust that blindly across a package boundary) is
    published to `<topic>.dlq`, never to its main topic, and the row is
    marked published (not retried — poison, not transient)."""
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()
    outbox.record(envelope)
    # Reach into the outbox's own storage to simulate a malformed row that
    # somehow bypassed `record`'s own validation — proves the drainer's OWN
    # defense-in-depth check actually runs, not merely `record`'s.
    event_id = envelope["event_id"]
    outbox._entries[event_id] = dict(envelope)  # noqa: SLF001 — white-box test setup
    del outbox._entries[event_id]["trace_id"]  # noqa: SLF001

    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.dead_lettered == (event_id,)
    assert result.published == ()
    topics_published = [topic for topic, _ in publisher.published]
    assert topics_published == [dlq_topic_for(envelope["event_type"])]
    assert outbox.list_pending() == ()


def test_topic_producer_mismatch_rejected_to_dlq() -> None:
    """A syntactically-valid-but-wrong producer is rejected (ADR-0013 1:1
    rule) — routed to DLQ, never published to the main topic."""
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()
    outbox.record(envelope)
    event_id = envelope["event_id"]
    tampered = dict(envelope)
    tampered["producer"] = "some-other-service"
    outbox._entries[event_id] = tampered  # noqa: SLF001 — white-box test setup

    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.dead_lettered == (event_id,)
    topics_published = [topic for topic, _ in publisher.published]
    assert topics_published == [dlq_topic_for(envelope["event_type"])]


def test_unknown_event_type_rejected_to_dlq() -> None:
    """An `event_type` that is not a declared AsyncAPI channel at all is
    routed to the DLQ (falls back to `envelope.malformed.v1.dlq` naming is
    NOT triggered here — `event_type` is present, just unknown, so
    `dlq_topic_for` still derives a `<event_type>.dlq` name)."""
    outbox = InMemoryOutbox()
    envelope = make_tenant_envelope()
    outbox.record(envelope)
    event_id = envelope["event_id"]
    tampered = dict(envelope)
    tampered["event_type"] = "no.such.channel.v1"
    outbox._entries[event_id] = tampered  # noqa: SLF001 — white-box test setup

    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.dead_lettered == (event_id,)
    topics_published = [topic for topic, _ in publisher.published]
    assert topics_published == [dlq_topic_for("no.such.channel.v1")]


def test_dlq_outage_leaves_row_pending_and_does_not_abort_the_batch() -> None:
    """SHOULD-FIX (w2-18 review): a DLQ publish failure for one poison
    envelope must not abort the rest of the drain batch — every OTHER
    envelope in `pending` is still processed within the same `drain_once`
    call, and the poison envelope itself is left pending (retried on the
    next drain), not silently dropped."""
    outbox = InMemoryOutbox()
    poison = make_tenant_envelope(idempotency_key="acme-co:run-1:poison")
    outbox.record(poison)
    poison_id = poison["event_id"]
    tampered = dict(poison)
    del tampered["trace_id"]
    outbox._entries[poison_id] = tampered  # noqa: SLF001 — white-box test setup

    healthy = make_tenant_envelope(idempotency_key="acme-co:run-1:healthy")
    outbox.record(healthy)

    publisher = AsyncFailingDLQPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    # The poison envelope's DLQ publish failed -> left pending, not dropped.
    assert poison_id in result.retried_pending
    assert poison_id not in result.dead_lettered
    pending_ids = {e["event_id"] for e in outbox.list_pending()}
    assert poison_id in pending_ids
    # The healthy envelope also failed (AsyncFailingDLQPublisher fails EVERY
    # publish call, main-topic included) but was still ATTEMPTED — proving
    # the batch was not aborted after the poison envelope's DLQ failure.
    assert healthy["event_id"] in result.retried_pending
    assert len(publisher.attempts) == 2


def test_aggregate_under_threshold_never_published() -> None:
    """A k-anonymity-suppressed aggregate envelope must NOT be published —
    not to its main topic, not to the DLQ either (privacy at the bus
    boundary)."""
    outbox = InMemoryOutbox()
    envelope = make_suppressed_aggregate_envelope()
    outbox.record(envelope)
    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.suppressed == (envelope["event_id"],)
    assert result.published == ()
    assert result.dead_lettered == ()
    assert publisher.published == ()
    # Marked published so it is never retried (deterministic guard verdict).
    assert outbox.list_pending() == ()


def test_aggregate_pending_review_never_published() -> None:
    """A `pending_review` aggregate envelope must NOT be published — not to
    its main topic, not to the DLQ (same "never published anywhere" outcome
    as under-threshold, distinct rejection reason)."""
    outbox = InMemoryOutbox()
    envelope = make_pending_review_aggregate_envelope()
    outbox.record(envelope)
    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.suppressed == (envelope["event_id"],)
    assert result.published == ()
    assert result.dead_lettered == ()
    assert publisher.published == ()
    assert outbox.list_pending() == ()


def test_aggregate_suppressed_and_producer_mismatch_goes_nowhere() -> None:
    """Critic MUST-FIX: an aggregate envelope that is BOTH
    suppressed/under-threshold AND fails a structural/topic check (producer
    mismatch here) must go NOWHERE — not the main topic, not the DLQ. The
    privacy guard must fire FIRST, before the structural/topic check ever
    gets a chance to route it to the DLQ with cohort_size/
    aggregate_scope_id/payload intact."""
    outbox = InMemoryOutbox()
    envelope = make_suppressed_aggregate_envelope()
    outbox.record(envelope)
    event_id = envelope["event_id"]
    tampered = dict(envelope)
    tampered["producer"] = "some-other-service"
    outbox._entries[event_id] = tampered  # noqa: SLF001 — white-box test setup

    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.suppressed == (event_id,)
    assert result.dead_lettered == ()
    assert result.published == ()
    # Nothing was ever published anywhere — no main topic, no DLQ.
    assert publisher.published == ()
    assert outbox.list_pending() == ()


def test_aggregate_under_threshold_and_malformed_goes_nowhere() -> None:
    """Critic MUST-FIX: an aggregate envelope that is BOTH under-threshold
    AND structurally malformed (missing a required field) must go NOWHERE —
    not the main topic, not the DLQ."""
    outbox = InMemoryOutbox()
    envelope = make_suppressed_aggregate_envelope()
    outbox.record(envelope)
    event_id = envelope["event_id"]
    tampered = dict(envelope)
    del tampered["trace_id"]
    outbox._entries[event_id] = tampered  # noqa: SLF001 — white-box test setup

    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.suppressed == (event_id,)
    assert result.dead_lettered == ()
    assert result.published == ()
    assert publisher.published == ()
    assert outbox.list_pending() == ()


def test_aggregate_pending_review_and_malformed_goes_nowhere() -> None:
    """Same MUST-FIX scenario, `pending_review` status instead of
    under-threshold — still must go nowhere, not the DLQ."""
    outbox = InMemoryOutbox()
    envelope = make_pending_review_aggregate_envelope()
    outbox.record(envelope)
    event_id = envelope["event_id"]
    tampered = dict(envelope)
    tampered["producer"] = "some-other-service"
    outbox._entries[event_id] = tampered  # noqa: SLF001 — white-box test setup

    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.suppressed == (event_id,)
    assert result.dead_lettered == ()
    assert publisher.published == ()
    assert outbox.list_pending() == ()


def test_aggregate_above_threshold_is_published() -> None:
    outbox = InMemoryOutbox()
    envelope = make_aggregate_envelope()
    outbox.record(envelope)
    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.published == (envelope["event_id"],)
    assert publisher.published == ((envelope["event_type"], envelope),)


def test_system_envelope_drains_with_none_tenant_scope() -> None:
    outbox = InMemoryOutbox()
    envelope = make_system_envelope()
    outbox.record(envelope)
    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert result.published == (envelope["event_id"],)
    assert outbox.list_pending() == ()


def test_drain_once_processes_multiple_pending_envelopes() -> None:
    outbox = InMemoryOutbox()
    first = make_tenant_envelope(idempotency_key="acme-co:run-1:patch-unit-1")
    second = make_tenant_envelope(idempotency_key="acme-co:run-1:patch-unit-2")
    outbox.record(first)
    outbox.record(second)
    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once())

    assert set(result.published) == {first["event_id"], second["event_id"]}
    assert len(publisher.published) == 2


def test_drain_once_scoped_to_tenant() -> None:
    outbox = InMemoryOutbox()
    envelope_a = make_tenant_envelope(tenant_id="acme-co", run_id="run-a")
    envelope_b = make_tenant_envelope(
        tenant_id="globex-co",
        run_id="run-b",
        idempotency_key="globex-co:run-b:patch-unit-1",
    )
    outbox.record(envelope_a)
    outbox.record(envelope_b)
    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    result = asyncio.run(drainer.drain_once(TENANT_A))

    assert result.published == (envelope_a["event_id"],)
    # Tenant B's envelope was never even listed for this drain.
    assert outbox.list_pending(TenantId("globex-co")) == (envelope_b,)

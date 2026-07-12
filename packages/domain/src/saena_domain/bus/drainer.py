"""OutboxDrainer — outbox drain -> topic publish pump (W2C exit criterion).

Spec basis: `docs/architecture/implementation-waves.md` W2C exit ("outbox
drain→토픽 발행(3-context envelope 검증), consumer idempotency"), ADR-0013
(3-context envelope model, `event_type` == topic 1:1), ADR-0015 (DLQ naming
`<topic>.dlq`), ADR-0004 (Redpanda = data pool).

`OutboxDrainer.drain_once` pumps `OutboxPort.list_pending` once:

1. For each pending envelope, run structural + topic/producer validation
   (`saena_domain.bus._envelope_check`, locally-wired — see that module's
   docstring for why it does not import `saena_domain.events` privately).
   A FAILING envelope is poison: it is published to `<topic>.dlq`
   (`dlq_topic_for`) instead of its intended topic, and the source outbox
   row is marked published (never retried — the same malformed envelope
   will fail the same check again on the next drain, forever, if left
   pending).
2. `context_type: aggregate` envelopes additionally pass
   `saena_domain.privacy.guard_aggregate_publish` (k-anonymity gate,
   ADR-0013) BEFORE publish. A suppressed/under-threshold/not-yet-decided
   aggregate envelope is NEVER published — not to its main topic, not to the
   DLQ either (module docstring rationale: the DLQ is itself a durable,
   at-least-once-replayed topic; re-publishing a privacy-suppressed
   aggregate there would recreate the exact re-identification exposure the
   guard exists to prevent). The source outbox row IS marked published
   (never retried — the guard's verdict will not change by retrying the same
   cohort numbers).
3. A structurally-valid, guard-passing envelope is published to its main
   topic (`topic == envelope["event_type"]`, ADR-0013 1:1 rule). SUCCESS ->
   `OutboxPort.mark_published`. FAILURE (`PublishFailedError`, e.g. broker
   unreachable) -> the outbox row is left pending, retried on the next
   `drain_once` call (at-least-once semantics, W2C exit criterion) — this is
   the ONLY outcome that does not advance the row's published state.

Retry/backoff policy (documented, not implemented — task spec: "note max
attempts; poison after N -> DLQ"): this drainer has NO built-in attempt
counter or max-attempts threshold. A transient `PublishFailedError` (broker
down, timeout) simply leaves the row pending indefinitely — every future
`drain_once` call retries it again with no backoff of its own (the CALLER
controls drain cadence, e.g. a poll loop with its own sleep/backoff between
`drain_once` calls). A row that is valid-but-persistently-unpublishable
(e.g. the target topic itself is misconfigured/deleted) will retry forever
under this drainer alone; operating this safely in production requires an
external attempt-count/backoff policy (e.g. tracked in a sidecar counter or
observability alert on "row pending > N drains") — OUT OF SCOPE for this
patch unit, tracked here as an explicit open item. This is different from
the poison case (`EnvelopeRejectedError`/`AggregatePublishSuppressedError`),
which is recognized and DLQ-routed/dropped on the FIRST attempt, not after N
retries — poison is detected structurally (malformed shape, topic mismatch,
suppressed privacy verdict), not by attempt-counting.

Both sync (`InMemoryOutbox`) and async (`PostgresOutbox`) `OutboxPort`
implementations are supported transparently — `_maybe_await` awaits a
coroutine result, passes a plain value through unchanged, so `OutboxDrainer`
itself is written once against the Protocol shape and works against either
concrete adapter without an `if isinstance(...)` branch at every call site.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from saena_domain.bus._envelope_check import structural_errors, topic_producer_errors
from saena_domain.bus.errors import (
    AggregatePublishSuppressedError,
    EnvelopeRejectedError,
    PublishFailedError,
)
from saena_domain.bus.publisher import Publisher, dlq_topic_for
from saena_domain.identity import TenantId
from saena_domain.privacy import PrivacyGuardError, guard_aggregate_publish


async def _maybe_await(value: Any) -> Any:
    """Await `value` if it is a coroutine (async `OutboxPort` methods, e.g.
    `PostgresOutbox`), else return it unchanged (sync methods, e.g.
    `InMemoryOutbox`) — see module docstring."""
    if inspect.isawaitable(value):
        return await value
    return value


@runtime_checkable
class _OutboxLike(Protocol):
    """Structural shape this drainer needs from an `OutboxPort` — sync OR
    async method bodies, both accepted (see `_maybe_await`)."""

    def list_pending(self, tenant_id: TenantId | None = None) -> Any: ...

    def mark_published(self, tenant_id: TenantId | None, event_id: str) -> Any: ...


def _envelope_owner(envelope: dict[str, Any]) -> TenantId | None:
    """The owning `tenant_id` for `mark_published`'s first argument, mirroring
    `saena_domain.persistence.memory._envelope_owner`/`postgres.adapters.
    _envelope_owner` exactly (`context_type: tenant` -> that tenant;
    `system`/`aggregate` -> `None`)."""
    if envelope.get("context_type") == "tenant":
        owner = envelope.get("tenant_id")
        if isinstance(owner, str):
            return TenantId(owner)
    return None


@dataclass(frozen=True, slots=True)
class DrainResult:
    """Outcome tally for one `drain_once` call — observability/testing aid,
    not itself consumed by any control-flow decision in this module."""

    published: tuple[str, ...]
    """`event_id`s successfully published to their main topic."""

    dead_lettered: tuple[str, ...]
    """`event_id`s routed to `<topic>.dlq` (poison: malformed shape or
    topic/producer mismatch)."""

    suppressed: tuple[str, ...]
    """`event_id`s that failed the aggregate k-anonymity publish guard —
    never published anywhere."""

    retried_pending: tuple[str, ...]
    """`event_id`s left pending after a `PublishFailedError` — will be
    retried on the next `drain_once` call."""


class OutboxDrainer:
    """Pumps `OutboxPort.list_pending` -> validate -> `Publisher.publish` ->
    `OutboxPort.mark_published`, once per `drain_once` call."""

    def __init__(self, outbox: _OutboxLike, publisher: Publisher) -> None:
        self._outbox = outbox
        self._publisher = publisher

    async def drain_once(self, tenant_id: TenantId | None = None) -> DrainResult:
        pending = await _maybe_await(self._outbox.list_pending(tenant_id))

        published: list[str] = []
        dead_lettered: list[str] = []
        suppressed: list[str] = []
        retried_pending: list[str] = []

        for envelope in pending:
            event_id = envelope["event_id"]
            owner = _envelope_owner(envelope)

            reject_messages = structural_errors(envelope)
            if not reject_messages:
                reject_messages = topic_producer_errors(envelope)

            if reject_messages:
                await self._route_to_dlq(envelope, reject_messages)
                await _maybe_await(self._outbox.mark_published(owner, event_id))
                dead_lettered.append(event_id)
                continue

            if envelope.get("context_type") == "aggregate":
                try:
                    guard_aggregate_publish(envelope)
                except PrivacyGuardError as exc:
                    # Never published anywhere (not even the DLQ — see module
                    # docstring rationale). Row is marked published so it is
                    # never retried; the guard's verdict is deterministic
                    # given the same cohort numbers, so retrying cannot help.
                    _ = AggregatePublishSuppressedError(
                        f"aggregate envelope {event_id!r} suppressed by k-anonymity "
                        f"publish guard: {exc}",
                        context={"event_id": event_id},
                    )
                    await _maybe_await(self._outbox.mark_published(owner, event_id))
                    suppressed.append(event_id)
                    continue

            topic = envelope["event_type"]
            try:
                await self._publisher.publish(topic, envelope)
            except PublishFailedError:
                # At-least-once semantics: NEVER mark published on a publish
                # failure — the row stays pending, retried on the next drain.
                retried_pending.append(event_id)
                continue

            await _maybe_await(self._outbox.mark_published(owner, event_id))
            published.append(event_id)

        return DrainResult(
            published=tuple(published),
            dead_lettered=tuple(dead_lettered),
            suppressed=tuple(suppressed),
            retried_pending=tuple(retried_pending),
        )

    async def _route_to_dlq(self, envelope: dict[str, Any], messages: list[str]) -> None:
        """Publish `envelope` to `<topic>.dlq` (ADR-0015). If `event_type` is
        itself missing/malformed (so no sensible topic name can be derived
        at all), falls back to a fixed `"envelope.malformed.v1.dlq"` sink so
        even a maximally-broken envelope still reaches SOME DLQ rather than
        being silently swallowed.

        A DLQ publish failure itself is NOT retried by this drainer (poison
        routing is a best-effort side channel, not the at-least-once-critical
        path `drain_once`'s main-topic publish is) — it propagates as
        `PublishFailedError` to the caller of `drain_once`, surfacing the DLQ
        outage loudly rather than silently dropping the poison envelope AND
        silently leaving the source row stuck.
        """
        event_type = envelope.get("event_type")
        topic = (
            dlq_topic_for(event_type)
            if isinstance(event_type, str)
            else "envelope.malformed.v1.dlq"
        )
        rejection = EnvelopeRejectedError(
            f"envelope {envelope.get('event_id')!r} rejected at drain time: " + "; ".join(messages),
            context={"event_id": envelope.get("event_id"), "messages": messages},
        )
        dlq_envelope = dict(envelope)
        dlq_envelope["_dlq_reason"] = rejection.to_dict()
        await self._publisher.publish(topic, dlq_envelope)


__all__ = ["DrainResult", "OutboxDrainer"]

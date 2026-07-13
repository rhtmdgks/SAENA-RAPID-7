"""Publisher port + adapters — topic dispatch for validated envelopes (W2C).

Spec basis: `docs/architecture/implementation-waves.md` W2C exit ("outbox
drain→토픽 발행(3-context envelope 검증), consumer idempotency"), ADR-0013
(`event_type` == AsyncAPI topic name, 1:1 mapping — no double management),
ADR-0004 (Redpanda = data pool component), ADR-0015 (DLQ naming
`<topic>.dlq`, wiring deferred to W2C — this module is that wiring).

`Publisher` is a `typing.Protocol`: one async method, `publish(topic,
envelope)`. Two concrete adapters:

- `InMemoryPublisher` — pure in-process reference implementation. Records
  every published `(topic, envelope)` pair in call order; used by unit tests
  and any pre-Redpanda caller. Never raises for a well-formed call (a test
  that needs to exercise `OutboxDrainer`'s publish-failure retry path injects
  a small wrapper/subclass that raises on demand — see
  `tests/unit/domain_bus/bus_factories.py`).
- `RedpandaPublisher` — thin `aiokafka.AIOKafkaProducer` wrapper. Configured
  via an injected `RedpandaConfig` dataclass (bootstrap servers + optional
  SASL/TLS material passed through as opaque strings the caller already
  resolved from a secret store) — this module NEVER reads environment
  variables or embeds credentials itself (CLAUDE.md Constraints: "Secrets
  never in prompts... audit payloads"; the same discipline applies to source
  code — no hardcoded broker addresses or credentials here).

Topic selection (ADR-0013 1:1 rule): `topic == envelope["event_type"]` for a
publish to a MAIN topic. Publishing to a DLQ uses `<topic>.dlq` (ADR-0015) —
callers (here, `OutboxDrainer`) compute that name via `dlq_topic_for`, this
module does not special-case DLQ topic strings itself; a `Publisher` treats
every `topic` argument identically (just a destination string), keeping the
DLQ-naming policy entirely in the drainer/caller layer where ADR-0015 places
it.

Partition-key choice — FLAGGED, NOT a finalized architecture decision
(`docs/architecture/resilience.md:25`/:42 explicitly lists "partition key
규약" as an OPEN DECISION, deferred past this patch unit — this module picks
a reasonable default so w2-18 has SOMETHING concrete to ship and test
against, it does not close that open decision): `key =
envelope["idempotency_key"]` when present (every ADR-0013 v1 envelope
carries a non-empty `idempotency_key` — the 8th common field, frozen), else
falling back to `tenant_id` for `context_type: tenant` envelopes. Rationale
for THIS default (subject to revision when resilience.md's open decision is
actually confirmed): the idempotency key is unique per logical event, which
is a stronger, more evenly-distributed partitioning key than `tenant_id`
alone would be for a tenant with many concurrent events — but it trades away
per-tenant ORDERING (two different events for the same tenant can land on
different partitions, so a consumer relying on same-tenant event ordering
cannot assume it from this key choice alone). `context_type: system`/
`aggregate` envelopes have no `tenant_id` at all, so `idempotency_key` is
their only available key regardless of which way the open decision resolves.
Tracked as a w2-20 follow-up item per critic review (w2-18) — do not treat
this module's current behavior as the confirmed partition-key convention.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]

from saena_domain.bus.errors import PublishFailedError


def partition_key_for(envelope: dict[str, Any]) -> bytes | None:
    """Derive the producer partition key for `envelope` (see module docstring
    "Partition-key choice").

    Returns `None` only if `envelope` carries neither a non-empty
    `idempotency_key` nor a `tenant_id` — every schema-valid ADR-0013
    envelope has at least `idempotency_key`, so `None` should never occur in
    practice; it is handled explicitly (rather than raising) so a caller
    publishing a malformed envelope to the DLQ never crashes on key
    derivation itself.
    """
    idempotency_key = envelope.get("idempotency_key")
    if isinstance(idempotency_key, str) and idempotency_key:
        return idempotency_key.encode("utf-8")
    tenant_id = envelope.get("tenant_id")
    if isinstance(tenant_id, str) and tenant_id:
        return tenant_id.encode("utf-8")
    return None


def dlq_topic_for(topic: str) -> str:
    """`<topic>.dlq` — ADR-0015 DLQ naming convention."""
    return f"{topic}.dlq"


@runtime_checkable
class Publisher(Protocol):
    """Topic-publish port. One method: hand a validated envelope to `topic`."""

    async def publish(self, topic: str, envelope: dict[str, Any]) -> None:
        """Publish `envelope` to `topic`.

        Raises `saena_domain.bus.errors.PublishFailedError` (never a bare
        transport exception) on any failure to hand the message to the
        broker — callers (`OutboxDrainer`) rely on this exact exception type
        to decide "leave the outbox row pending, retry later".
        """
        ...


class InMemoryPublisher:
    """Reference `Publisher` — records every publish in-process, no I/O.

    `published` is an append-only tuple of `(topic, envelope)` pairs in
    publish order — a deep copy of `envelope` is stored so a caller mutating
    the dict it passed to `publish` after the call returns can never
    retroactively change what this adapter recorded (same defensive-copy
    discipline as `saena_domain.persistence.memory.InMemoryOutbox`).
    """

    def __init__(self) -> None:
        self._published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, topic: str, envelope: dict[str, Any]) -> None:
        self._published.append((topic, copy.deepcopy(envelope)))

    @property
    def published(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        return tuple(self._published)


@dataclass(frozen=True, slots=True)
class RedpandaConfig:
    """Injected Redpanda/Kafka producer configuration — no secrets embedded
    in this module; callers resolve `sasl_plain_password` etc. from their own
    secret store and pass the resolved value through.

    `bootstrap_servers` accepts aiokafka's own comma-separated-string-or-list
    form unchanged. `extra_producer_kwargs` is an escape hatch for any
    `AIOKafkaProducer` constructor keyword this dataclass does not name
    explicitly (e.g. `acks`, `enable_idempotence`) — kept as a plain dict
    rather than growing this dataclass's field list indefinitely.

    `sasl_plain_username`/`sasl_plain_password` are `field(repr=False)`
    (SHOULD-FIX, w2-18 review) — CLAUDE.md Constraints ("Secrets never in
    prompts, Helm values plaintext, audit payloads") applies equally to an
    accidental `repr()`/traceback dump of this dataclass (e.g. an unhandled
    exception during producer construction, or a debug log statement that
    naively `%s`-formats a `RedpandaConfig` instance) — neither field's
    value is ever included in the generated `__repr__`/`__str__`.
    """

    bootstrap_servers: str | list[str]
    client_id: str | None = None
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: str | None = None
    sasl_plain_username: str | None = field(default=None, repr=False)
    sasl_plain_password: str | None = field(default=None, repr=False)
    extra_producer_kwargs: dict[str, Any] = field(default_factory=dict)

    def producer_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "bootstrap_servers": self.bootstrap_servers,
            "security_protocol": self.security_protocol,
            **self.extra_producer_kwargs,
        }
        if self.client_id is not None:
            kwargs["client_id"] = self.client_id
        if self.sasl_mechanism is not None:
            kwargs["sasl_mechanism"] = self.sasl_mechanism
        if self.sasl_plain_username is not None:
            kwargs["sasl_plain_username"] = self.sasl_plain_username
        if self.sasl_plain_password is not None:
            kwargs["sasl_plain_password"] = self.sasl_plain_password
        return kwargs


class RedpandaPublisher:
    """`Publisher` over `aiokafka.AIOKafkaProducer` (targets Redpanda —
    ADR-0004 data pool — but speaks the plain Kafka wire protocol Redpanda is
    compatible with; nothing here is Redpanda-specific beyond the topic
    naming/partitioning conventions documented above).

    Lifecycle: `start()` must be called (once) before the first `publish`;
    `stop()` releases the underlying client. Usable as an async context
    manager (`async with RedpandaPublisher(config) as publisher: ...`) for
    callers that want automatic start/stop. `start()`/`stop()` apply
    uniformly regardless of whether `producer` was injected (test double) or
    built internally from `config` — an injected `producer` is NOT assumed
    pre-started, so unit tests can exercise the real start/stop/not-started
    guard logic against a fake `AIOKafkaProducer`-shaped double without a
    live broker (see `tests/unit/domain_bus/test_publisher.py`).

    `value_serializer`: envelopes are JSON-encoded UTF-8 bytes
    (`json.dumps(envelope, sort_keys=False).encode("utf-8")`) — plain JSON,
    matching every other transport this codebase uses for envelopes (no
    Avro/Protobuf schema registry in v1 scope).
    """

    def __init__(self, config: RedpandaConfig, *, producer: AIOKafkaProducer | None = None) -> None:
        self._config = config
        self._producer = producer if producer is not None else self._build_producer(config)
        self._started = False

    @staticmethod
    def _build_producer(config: RedpandaConfig) -> AIOKafkaProducer:
        import json

        def _serialize(value: dict[str, Any]) -> bytes:
            return json.dumps(value, sort_keys=False).encode("utf-8")

        return AIOKafkaProducer(value_serializer=_serialize, **config.producer_kwargs())

    async def start(self) -> None:
        if self._started:
            return
        await self._producer.start()
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        await self._producer.stop()
        self._started = False

    async def __aenter__(self) -> RedpandaPublisher:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def publish(self, topic: str, envelope: dict[str, Any]) -> None:
        if not self._started:
            raise PublishFailedError(
                "RedpandaPublisher.publish called before start() — producer not connected",
                context={"topic": topic},
            )
        key = partition_key_for(envelope)
        try:
            await self._producer.send_and_wait(topic, value=envelope, key=key)
        except Exception as exc:  # noqa: BLE001 — deliberately broad: every
            # aiokafka transport failure (KafkaTimeoutError, KafkaConnectionError,
            # etc.) must surface as the SAME PublishFailedError to the drainer, so
            # it always leaves the outbox row pending on ANY publish failure —
            # narrowing this to a specific aiokafka exception subset would risk
            # silently NOT retrying a transient failure type this module's author
            # did not anticipate (at-least-once semantics, W2C exit criterion).
            raise PublishFailedError(
                f"publish to topic {topic!r} failed: {exc}",
                context={"topic": topic, "event_id": envelope.get("event_id")},
            ) from exc


__all__ = [
    "InMemoryPublisher",
    "Publisher",
    "RedpandaConfig",
    "RedpandaPublisher",
    "dlq_topic_for",
    "partition_key_for",
]

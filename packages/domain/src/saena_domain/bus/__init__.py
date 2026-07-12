"""saena_domain.bus — outbox drain -> Redpanda publish + consumer idempotency (w2-18, W2C).

Spec basis: `docs/architecture/implementation-waves.md` W2C exit ("outbox
drain→토픽 발행(3-context envelope 검증), consumer idempotency"), ADR-0013
(event envelope v1, `event_type` == topic 1:1), ADR-0015 (DLQ naming
`<topic>.dlq`, wiring), ADR-0004 (Redpanda = data pool). Builds directly on
top of `saena_domain.persistence` (`OutboxPort`, W2A "recording only" scope)
and `saena_domain.events`/`saena_domain.privacy` (envelope + k-anonymity
validation) — this package is the first one in the domain library that
actually talks to a message broker.

Public API:

- Publisher: `Publisher` (port), `InMemoryPublisher` (test reference),
  `RedpandaPublisher` + `RedpandaConfig` (`aiokafka` adapter), `dlq_topic_for`,
  `partition_key_for`.
- Drain: `OutboxDrainer`, `DrainResult`.
- Consumer idempotency: `IdempotentConsumer`, `Handler`,
  `SYSTEM_SCOPE_TENANT_ID`.
- Errors: `BusError`, `EnvelopeRejectedError`, `PublishFailedError`,
  `AggregatePublishSuppressedError`.
"""

from __future__ import annotations

from saena_domain.bus.consumer import SYSTEM_SCOPE_TENANT_ID, Handler, IdempotentConsumer
from saena_domain.bus.drainer import DrainResult, OutboxDrainer
from saena_domain.bus.errors import (
    AggregatePublishSuppressedError,
    BusError,
    EnvelopeRejectedError,
    PublishFailedError,
)
from saena_domain.bus.publisher import (
    InMemoryPublisher,
    Publisher,
    RedpandaConfig,
    RedpandaPublisher,
    dlq_topic_for,
    partition_key_for,
)

__all__ = [
    "SYSTEM_SCOPE_TENANT_ID",
    "AggregatePublishSuppressedError",
    "BusError",
    "DrainResult",
    "EnvelopeRejectedError",
    "Handler",
    "IdempotentConsumer",
    "InMemoryPublisher",
    "OutboxDrainer",
    "Publisher",
    "PublishFailedError",
    "RedpandaConfig",
    "RedpandaPublisher",
    "dlq_topic_for",
    "partition_key_for",
]

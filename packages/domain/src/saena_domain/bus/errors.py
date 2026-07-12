"""Exception hierarchy for `saena_domain.bus`.

Mirrors `saena_domain.persistence.errors`'s shape (`saena.<category>.<reason>`
`error_code` + structured, log-safe `context` dict, ADR-0015 taxonomy) so a
services-layer problem-detail mapper can reuse these verbatim — see
`saena_domain/persistence/errors.py` module docstring for the rationale this
module follows.
"""

from __future__ import annotations

from typing import Any


class BusError(Exception):
    """Base class for every error raised by `saena_domain.bus`.

    Attributes:
        error_code: `saena.<category>.<reason>` taxonomy string (ADR-0015),
            reusable verbatim as a services-layer ProblemDetail `error_code`.
        context: structured, log-safe data describing the failure. Callers
            building an audit event or a DLQ record read this dict rather
            than parsing the exception message.
    """

    error_code: str = "saena.bus.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class EnvelopeRejectedError(BusError):
    """An envelope failed drain-time validation and was routed to the DLQ
    (`<topic>.dlq`, ADR-0015) instead of its intended topic.

    Raised for structurally-malformed envelopes (dual jsonschema+pydantic
    validation failure via `saena_domain.events`) and for
    topic/producer/event_type mismatches (ADR-0013 1:1 topic mapping) — both
    are "poison" conditions a retry can never fix, so `OutboxDrainer` marks
    the source outbox row published (never retried) after successfully
    routing it to the DLQ.
    """

    error_code = "saena.bus.envelope_rejected"


class PublishFailedError(BusError):
    """A publish attempt to the target topic (main or DLQ) failed.

    At-least-once semantics (W2C exit criterion): `OutboxDrainer` never marks
    an outbox row published when this is raised — the row stays pending and
    is retried on the next drain. Distinct from `EnvelopeRejectedError`
    (poison, not retried) — a `PublishFailedError` is a transient transport
    condition (broker unavailable, timeout, etc.) that a later drain may
    succeed at.
    """

    error_code = "saena.bus.publish_failed"


class AggregatePublishSuppressedError(BusError):
    """An `AggregateContext` envelope failed the k-anonymity publish guard
    (`saena_domain.privacy.guard_aggregate_publish`, ADR-0013) and must never
    reach any topic — not even the DLQ, since the DLQ is itself a durable,
    at-least-once-replayed topic and re-publishing a suppressed aggregate
    there would be the exact re-identification leak the guard exists to
    prevent.

    `OutboxDrainer` marks the source outbox row published (never retried —
    the cohort will never un-suppress itself by retrying) after raising this
    for observability purposes only; no bytes are ever produced to any
    topic.
    """

    error_code = "saena.bus.aggregate_publish_suppressed"


__all__ = [
    "AggregatePublishSuppressedError",
    "BusError",
    "EnvelopeRejectedError",
    "PublishFailedError",
]

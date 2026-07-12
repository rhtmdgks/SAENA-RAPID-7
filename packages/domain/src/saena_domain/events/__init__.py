"""saena_domain.events — event envelope construction (ADR-0013 v1).

Public API:
    EnvelopeFactory        — build_tenant_envelope / build_system_envelope /
                              build_aggregate_envelope
    generate_uuid7          — RFC 9562 UUIDv7 generator
    is_valid_uuid7          — matches the envelope contract's event_id pattern
    EnvelopeError           — base exception
    EnvelopeValidationError — dual (jsonschema + pydantic) validation failure
    TopicMismatchError      — event_type not a declared AsyncAPI channel
    ProducerMismatchError   — producer != expected producer for event_type
    EngineNotPermittedError — payload.engine_id outside the v1 closed enum
    EngineIdRequiredError   — payload.engine_id missing on a channel that
                              requires it (x-saena-engine-id-required, ADR-0013
                              observation/citation/experiment families)
    PayloadDuplicatesEnvelopeFieldError — payload re-projects tenant_id/run_id

Out of scope for this module (task spec, ADR-0013 §Current decision
"k-anonity 게이트의 스키마 한계"): the `cohort_size >= privacy_threshold`
runtime gate for AggregateContext envelopes is explicitly deferred to W2A —
`build_aggregate_envelope` accepts and structurally validates both fields but
does not enforce their relationship.
"""

from __future__ import annotations

from saena_domain.events._uuid7 import generate_uuid7, is_valid_uuid7
from saena_domain.events.errors import (
    EngineIdRequiredError,
    EngineNotPermittedError,
    EnvelopeError,
    EnvelopeValidationError,
    PayloadDuplicatesEnvelopeFieldError,
    ProducerMismatchError,
    TopicMismatchError,
)
from saena_domain.events.factory import EnvelopeFactory

__all__ = [
    "EngineIdRequiredError",
    "EngineNotPermittedError",
    "EnvelopeError",
    "EnvelopeFactory",
    "EnvelopeValidationError",
    "PayloadDuplicatesEnvelopeFieldError",
    "ProducerMismatchError",
    "TopicMismatchError",
    "generate_uuid7",
    "is_valid_uuid7",
]

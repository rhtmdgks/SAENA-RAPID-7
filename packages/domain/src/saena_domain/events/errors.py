"""Error types raised by `saena_domain.events` envelope construction/validation."""

from __future__ import annotations


class EnvelopeError(Exception):
    """Base class for all `saena_domain.events` errors."""


class EnvelopeValidationError(EnvelopeError):
    """A built envelope failed dual validation (jsonschema and/or pydantic).

    Raised by `EnvelopeFactory` after both the JSON Schema (2020-12, via a
    locally-resolved `referencing.Registry` — no network fetch) and the
    generated pydantic envelope model
    (`saena_schemas.envelope.event_envelope_v1.SaenaEventEnvelopeV1`) have
    had a chance to run; carries every error message collected from
    whichever validator(s) failed.
    """

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__("; ".join(messages) if messages else "envelope validation failed")


class TopicMismatchError(EnvelopeError):
    """`event_type` does not equal a declared AsyncAPI channel/topic name.

    ADR-0013 §Current decision: "이 값[event_type]은 AsyncAPI 토픽 이름과
    항상 동일해야 한다(1:1 매핑, 이중 관리 금지)."
    """

    def __init__(self, event_type: str) -> None:
        self.event_type = event_type
        super().__init__(
            f"event_type {event_type!r} does not match any channel address in "
            "packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml"
        )


class ProducerMismatchError(EnvelopeError):
    """`producer` does not match the expected producer for `event_type`.

    The expected producer per topic is derived from the AsyncAPI
    `operations.*.summary` text (e.g. "agent-runner-service produces
    patch.unit.completed.v1") — see `saena_domain.events._topics`.
    """

    def __init__(self, event_type: str, producer: str, expected_producer: str) -> None:
        self.event_type = event_type
        self.producer = producer
        self.expected_producer = expected_producer
        super().__init__(
            f"producer {producer!r} is not the expected producer "
            f"{expected_producer!r} for event_type {event_type!r}"
        )


class EngineNotPermittedError(EnvelopeError):
    """`payload.engine_id` is outside the v1 closed enum.

    ADR-0013 §Current decision "engine_id": closed enum `["chatgpt-search"]`
    (v1 single value). CLAUDE.md "Engine scope (v1)": Google AI Overviews /
    Google AI Mode / Gemini are disabled — optimize/observe/claim forbidden.
    Engine addition requires separate re-approval + ADR + major version bump
    (ADR-0012 enum-widening-is-major rule); this error is the runtime-side
    enforcement of that closed enum ahead of/independent from schema
    rejection.
    """

    def __init__(self, engine_id: str) -> None:
        self.engine_id = engine_id
        super().__init__(
            f"engine_id {engine_id!r} is not permitted in v1 "
            "(closed enum: 'chatgpt-search' only — CLAUDE.md Engine scope v1)"
        )


class EngineIdRequiredError(EnvelopeError):
    """`payload.engine_id` is missing for a channel that requires it.

    ADR-0013 §Current decision "engine_id": "observation·citation·experiment
    계열 이벤트 **payload**에 필수." The AsyncAPI catalog marks exactly 3
    CONFIRMED v1 channels with `x-saena-engine-id-required: true`
    (`observation.captured.v1`, `citation.normalized.v1`,
    `experiment.outcome.observed.v1`, see
    `packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml`) — this is
    the runtime-side enforcement of that requirement, distinct from
    `EngineNotPermittedError` (present-but-wrong-value).
    """

    def __init__(self, event_type: str) -> None:
        self.event_type = event_type
        super().__init__(
            f"event_type {event_type!r} requires payload.engine_id to be present "
            "(ADR-0013 — observation/citation/experiment event families)"
        )


class PayloadDuplicatesEnvelopeFieldError(EnvelopeError):
    """`payload` re-projects an envelope-level identifier (ADR-0024(e)-1).

    "events/ 하위 이벤트 payload 스키마는 envelope가 이미 나르는
    tenant_id/run_id를 payload 안에 재투영(duplicate)하지 않는다."
    """

    def __init__(self, field_name: str) -> None:
        self.field_name = field_name
        super().__init__(
            f"payload must not duplicate envelope field {field_name!r} "
            "(ADR-0024(e)-1 — envelope already carries this identifier)"
        )

"""Exception hierarchy for `saena_domain.execution`.

Mirrors `saena_domain.identity.errors`' shape: every exception carries an
`error_code` (`saena.execution.<reason>`, ADR-0015 canonical error model
pattern) and a structured, log-safe `.context` dict — never free-text-only.
`to_dict()` gives a services-layer caller a ready-to-log/audit
representation without parsing the exception message.

These are *domain* errors (raised at construction/transition time by pure
functions and value objects in this package) — they never format HTTP
responses themselves (RFC 9457 problem+json mapping is a services-layer
concern, ADR-0015).
"""

from __future__ import annotations

from typing import Any


class ExecutionError(Exception):
    """Base class for every error raised by `saena_domain.execution`."""

    error_code: str = "saena.execution.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class JobContextValidationError(ExecutionError):
    """A `JobContext` field failed validation at construction time."""

    error_code = "saena.execution.job_context_invalid"


class InvalidJobTransitionError(ExecutionError):
    """`transition()` was asked for a `(current, target)` pair not on the
    lifecycle's allowed-transitions table (`saena_domain.execution.lifecycle`).
    """

    error_code = "saena.execution.invalid_transition"

    def __init__(self, current: object, target: object) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"invalid job transition: cannot move from {current!r} to {target!r}",
            context={"current": str(current), "target": str(target)},
        )


class JobErrorValidationError(ExecutionError):
    """A `JobError` value failed validation at construction time (bad
    `error_code` shape/category, oversized or stack-trace-shaped text)."""

    error_code = "saena.execution.job_error_invalid"


class ResourceLimitsValidationError(ExecutionError):
    """A `ResourceLimits` value failed validation at construction time."""

    error_code = "saena.execution.resource_limits_invalid"


class EngineNotPermittedError(ExecutionError):
    """`engine_id` is outside the v1 closed enum (`chatgpt-search` only).

    ADR-0013 §Current decision "engine_id": closed enum `["chatgpt-search"]`
    (v1 single value). CLAUDE.md "Engine scope (v1)".
    """

    error_code = "saena.execution.engine_not_permitted"

    def __init__(self, engine_id: str) -> None:
        self.engine_id = engine_id
        super().__init__(
            f"engine_id {engine_id!r} is not permitted in v1 (closed enum: "
            "'chatgpt-search' only — ADR-0013, CLAUDE.md Engine scope v1)",
            context={"engine_id": engine_id},
        )


class EngineDisallowedError(EngineNotPermittedError):
    """`engine_id` is one of the CLAUDE.md-named disabled engine families
    (Google AI Overviews / Google AI Mode / Gemini) — a more specific
    rejection than the generic `EngineNotPermittedError` for an arbitrary
    unrecognized string.
    """

    error_code = "saena.execution.engine_disallowed"

    def __init__(self, engine_id: str, disallowed_name: str) -> None:
        self.disallowed_name = disallowed_name
        ExecutionError.__init__(
            self,
            f"engine_id {engine_id!r} ({disallowed_name}) is explicitly disabled "
            "in v1 (CLAUDE.md Engine scope: optimize/observe/claim forbidden)",
            context={"engine_id": engine_id, "disallowed_name": disallowed_name},
        )
        self.engine_id = engine_id


class EventPayloadValidationError(ExecutionError):
    """A builder in `saena_domain.execution.events` produced (or was asked
    to produce) a payload that fails the bound `saena_schemas.event.*`
    pydantic model for its event type, or violates an AsyncAPI channel-layer
    rule (e.g. R4 failures-presence split) enforced at this layer."""

    error_code = "saena.execution.event_payload_invalid"


__all__ = [
    "EngineDisallowedError",
    "EngineNotPermittedError",
    "EventPayloadValidationError",
    "ExecutionError",
    "InvalidJobTransitionError",
    "JobContextValidationError",
    "JobErrorValidationError",
    "ResourceLimitsValidationError",
]

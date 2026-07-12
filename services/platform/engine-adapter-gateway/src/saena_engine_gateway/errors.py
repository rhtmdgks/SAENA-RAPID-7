"""Exception hierarchy for `saena_engine_gateway`.

Every error carries an `error_code` following the `saena.<category>.<reason>`
taxonomy (ADR-0015 canonical error model) and a structured, log-safe
`context` dict — mirroring the convention already established by
`saena_domain.identity.errors`/`saena_domain.events.errors`. The HTTP layer
(`saena_engine_gateway.problem_detail`) maps each of these to an RFC 9457
`application/problem+json` response; these classes themselves never format
HTTP responses or import FastAPI/starlette.
"""

from __future__ import annotations

from typing import Any


class EngineGatewayError(Exception):
    """Base class for every error raised by `saena_engine_gateway`.

    Attributes:
        error_code: `saena.<category>.<reason>` taxonomy string (ADR-0015),
            reused verbatim as the RFC 9457 `error_code` extension field.
        context: structured, log-safe data describing the violation —
            never customer source / secret material (ADR-0015 Constraints).
    """

    error_code: str = "saena.engine_gateway.error"
    #: Default RFC 9457 `status` for this error class; overridable per
    #: instance is unnecessary here since each subclass maps to exactly one
    #: HTTP status per the task's boundary-check design.
    http_status: int = 500
    #: ADR-0015 taxonomy default: unexpected/internal is non-retryable.
    retryable: bool = False

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class EngineNotPermittedError(EngineGatewayError):
    """`engine_id` is outside the v1 closed enum.

    Raised at adapter-registration time (`AdapterRegistry.register`),
    flag-creation time (`FlagRegistry.create`), and at the HTTP boundary
    (`GET/POST .../{engine_id}/...`) — the same guard applies uniformly at
    every entry point per ADR-0001's "single control point" framing and
    CLAUDE.md's "Engine scope (v1): ChatGPT Search only" operating
    principle. `google-ai-overviews` / `google-ai-mode` / `gemini` / any
    other non-enum value is rejected here, never merely hidden downstream.
    """

    error_code = "saena.policy_denied.engine_not_permitted"
    http_status = 403
    retryable = False

    def __init__(self, engine_id: str) -> None:
        self.engine_id = engine_id
        super().__init__(
            f"engine {engine_id!r} is not permitted in v1 "
            "(closed enum: 'chatgpt-search' only — CLAUDE.md Engine scope v1, ADR-0013)",
            context={"engine_id": engine_id},
        )


class AdapterNotFoundError(EngineGatewayError):
    """`engine_id` is within the closed enum but no adapter is registered
    for it in this `AdapterRegistry` instance."""

    error_code = "saena.not_found.adapter_missing"
    http_status = 404
    retryable = False

    def __init__(self, engine_id: str) -> None:
        self.engine_id = engine_id
        super().__init__(
            f"no adapter registered for engine_id {engine_id!r}",
            context={"engine_id": engine_id},
        )


class AdapterDisabledError(EngineGatewayError):
    """`engine_id` is enum-valid and an adapter is registered, but the
    per-adapter feature flag (ADR-0001 flag granularity = adapter unit) is
    off — resolution fails closed, never silently falls through."""

    error_code = "saena.policy_denied.adapter_disabled"
    http_status = 403
    retryable = False

    def __init__(self, engine_id: str) -> None:
        self.engine_id = engine_id
        super().__init__(
            f"adapter for engine_id {engine_id!r} is registered but its feature flag is off",
            context={"engine_id": engine_id},
        )


class PayloadEngineMismatchError(EngineGatewayError):
    """The request body's `engine_id` field is present but disagrees with
    the `{engine_id}` path parameter."""

    error_code = "saena.validation.engine_id_mismatch"
    http_status = 400
    retryable = False

    def __init__(self, path_engine_id: str, payload_engine_id: str) -> None:
        self.path_engine_id = path_engine_id
        self.payload_engine_id = payload_engine_id
        super().__init__(
            f"request body engine_id {payload_engine_id!r} does not match "
            f"path engine_id {path_engine_id!r}",
            context={
                "path_engine_id": path_engine_id,
                "payload_engine_id": payload_engine_id,
            },
        )

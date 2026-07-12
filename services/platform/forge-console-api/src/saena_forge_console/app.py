"""`create_app()` — FastAPI application factory (ADR-0007 v1 sole edge).

This module wires the full edge stack in the order request processing must
see it (outermost first):

    1. `trace_middleware`     -- resolves/generates trace_id + span_id,
                                  always writes `traceparent` back onto the
                                  response.
    2. `_TelemetryContextMiddleware` -- binds `saena_observability.
                                  TelemetryContext` (ADR-0016 required-
                                  attribute set) for the duration of the
                                  request, so every structured log emitted
                                  while handling it carries `saena.tenant_id`
                                  / `saena.context` implicitly (`saena_
                                  observability.logging.SaenaJsonFormatter`
                                  picks up the bound context automatically —
                                  no call site in this service passes
                                  `saena.*` attributes by hand).
    3. `tenant_reconciliation_middleware` -- `X-Saena-Tenant-Id` vs pod env
                                  `SAENA_TENANT_ID` (ADR-0014); 403 + audit-
                                  shaped log on mismatch.
    4. Route-level dependencies (`saena_forge_console.rbac.
       require_permission`) -- AuthN (header -> `ActorContext`) + RBAC
       default-deny, per route.
    5. `saena_forge_console.routes.router` -- run metadata, whoami, lineage.

Binding uses `saena.context="system"` (never `"tenant"`) at this generic
middleware layer even for tenant-scoped requests: the true tenant_id is not
yet reconciled/known this early in the pipeline (steps 2-3 run AFTER this
binding), and ADR-0016's `"tenant"` context REQUIRES a non-None
`saena.tenant_id` at bind time (`saena_observability.context._validate`) —
binding `"system"` with no identifiers is the only ADR-0016-legal choice
available before tenant reconciliation has run. Route handlers that need
tenant-scoped log correlation read `request.state.trace_id` directly
(`saena_forge_console.trace.resolve_trace_id`) rather than relying on a
`saena.tenant_id` log attribute this early middleware cannot yet supply.

A single `saena_forge_console.errors.ServiceError` exception handler maps
every raised error (from any layer above) to an RFC 9457 `problem+json`
body (ADR-0015) — this is the ONLY place a 4xx/5xx body gets constructed;
no route/dependency builds a response body of its own for an error case.
FastAPI's own `RequestValidationError` (422 on request-model validation
failure) is mapped through the same handler path so every error response
this service ever emits, including framework-generated ones, has the same
shape — WITHOUT echoing the raw offending value back to the caller (see
`_validation_error_handler`: `RequestValidationError.errors()` includes an
`"input"` key carrying the actual submitted value, which may be
secret-shaped; only `loc`/`type`/`msg` are ever included in the response
body/logs).

A catch-all `Exception` handler (`_unexpected_error_handler`) is also
registered so a genuine bug (an `AttributeError`, an unexpected error from
`RunStore`/`authorize()`/anything else not already wrapped in a
`ServiceError`) still produces a `problem+json` body via
`saena_forge_console.errors.internal_error` (ADR-0015 `internal` category)
instead of falling through to Starlette's default plaintext 500 — this is
what keeps "single place error bodies get built" true even for bugs this
service's own code did not anticipate. Per ADR-0015 Constraints (stack
traces / raw content never enter an audit-adjacent artifact): the response
body and the log line both carry a FIXED detail string, never
`str(exc))`/`repr(exc)`/a traceback — only the exception's TYPE NAME is
logged (safe: a Python class name is not user-controllable content).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from saena_observability import bind_telemetry_context, get_logger
from starlette.middleware.base import BaseHTTPMiddleware

from saena_forge_console.errors import (
    ServiceError,
    internal_error,
    to_problem_detail,
    validation_error,
)
from saena_forge_console.lineage import LineagePort, StubLineagePort
from saena_forge_console.routes import router
from saena_forge_console.run_store import RunStore
from saena_forge_console.tenant_reconcile import tenant_reconciliation_middleware
from saena_forge_console.trace import resolve_trace_id, trace_middleware

_logger = get_logger("saena_forge_console.app")

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


async def _telemetry_context_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    with bind_telemetry_context("system"):
        return await call_next(request)


def _sanitize_validation_errors(raw_errors: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip the raw offending VALUE out of `RequestValidationError.errors()`.

    Pydantic/FastAPI's own `.errors()` includes an `"input"` key (the actual
    submitted value that failed validation) and may include a `"ctx"` key
    (which can itself embed the offending value, e.g. `ctx.error` wrapping a
    `ValueError` built from the input). Both are dropped here — only
    `loc`/`type`/`msg` (a location path, the validator's type name, and a
    canned human-readable message; none of which round-trip caller-supplied
    content) survive into the problem+json body, so a secret-shaped or
    otherwise sensitive field value a caller submits can never echo back in
    this service's own error response (ADR-0015 Constraints:70 — "PII/secret
    원문 포함 금지").
    """
    return [
        {key: entry[key] for key in ("loc", "type", "msg") if key in entry} for entry in raw_errors
    ]


def _problem_response(request: Request, error: ServiceError) -> Response:
    trace_id = resolve_trace_id(request)
    problem = to_problem_detail(error, trace_id=trace_id, instance=str(request.url))
    # `error_code`/`status_code` are carried in the free-text `body` message
    # rather than as `saena.*` structured attributes: the ADR-0016 attribute
    # registry (`packages/observability/registry/attributes.json`) is an
    # allowlist this service does not own (single-owner principle, CLAUDE.md
    # #7) and neither name is a registered entry — `SaenaJsonFormatter`
    # would silently DROP an unregistered `saena.*` key (allowlist-first,
    # `saena_observability.redaction`), so putting them in `extra=` would
    # silently vanish from the emitted log line rather than error loudly.
    # `body` has no such allowlist (it is redacted via `redact_text`
    # pattern-scrubbing only, not the attribute allowlist), so it is the
    # correct place for this service-local, not-yet-registered detail.
    _logger.info("request error: error_code=%s status_code=%s", error.error_code, error.status_code)
    headers = dict(error.headers)
    return Response(
        content=problem.model_dump_json(exclude_none=True),
        status_code=error.status_code,
        media_type="application/problem+json",
        headers=headers,
    )


# Starlette's `BaseHTTPMiddleware` wraps a plain async function — these thin
# classes exist only so `add_middleware` (which expects a middleware class,
# not a bare callable) can register the function-style middlewares defined
# above/in their own modules without duplicating their logic here.


class _TraceMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any) -> None:
        super().__init__(app, dispatch=trace_middleware)


class _TelemetryContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any) -> None:
        super().__init__(app, dispatch=_telemetry_context_middleware)


class _TenantReconcileMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any) -> None:
        super().__init__(app, dispatch=tenant_reconciliation_middleware)


def create_app(
    *,
    run_store: RunStore | None = None,
    lineage_port: LineagePort | None = None,
) -> FastAPI:
    """Build the forge-console-api ASGI app.

    `run_store`/`lineage_port` are injected ports (task instruction: "run
    storage... simple dict adapter local to service"; "downstream resolution
    stubbed as injected port") -- tests supply their own instances (e.g.
    `saena_forge_console.lineage.InMemoryLineagePort`) so RBAC/tenant/trace
    behaviour can be tested without needing a real backing store, and so a
    future patch unit can swap in a real datastore-backed `RunStore` /
    audit-ledger `LineagePort` client without touching this factory's
    signature shape (only the default values change).
    """
    app = FastAPI(title="forge-console-api", version="0.1.0")
    app.state.run_store = run_store if run_store is not None else RunStore()
    app.state.lineage_port = lineage_port if lineage_port is not None else StubLineagePort()

    app.include_router(router)

    @app.exception_handler(ServiceError)
    async def _service_error_handler(request: Request, exc: ServiceError) -> Response:
        return _problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> Response:
        # Fixed detail string in the RESPONSE BODY -- never str(exc)/
        # exc.errors() verbatim, since the raw `.errors()` list carries an
        # "input" key (the actual offending value, possibly secret-shaped)
        # and may carry a "ctx" key that can itself embed that value.
        # Sanitized field-location context (loc/type/msg only -- see
        # `_sanitize_validation_errors`) is logged for operator
        # diagnosability, never included in the client-facing body.
        sanitized = _sanitize_validation_errors(exc.errors())
        _logger.info("request validation failed: fields=%s", sanitized)
        error = validation_error(
            "schema_mismatch",
            detail="request body failed schema validation",
        )
        return _problem_response(request, error)

    @app.exception_handler(Exception)
    async def _unexpected_error_handler(request: Request, exc: Exception) -> Response:
        # Catch-all: keeps "single place error bodies get built" true even
        # for a bug this service's own code did not anticipate (an
        # AttributeError, an unexpected error surfacing from RunStore/
        # authorize()/anything else not already a ServiceError). NEVER
        # includes str(exc)/repr(exc)/a traceback in the response body or
        # the log line -- only the exception's TYPE NAME is logged (a
        # Python class name is not user-controllable content, unlike the
        # exception's own message, which could echo attacker-supplied
        # input). ADR-0015 Constraints: stack traces / raw content never
        # enter an audit-adjacent artifact.
        _logger.warning("unexpected error: exception_type=%s", type(exc).__name__)
        error = internal_error(
            "unexpected", detail="an unexpected error occurred while handling this request"
        )
        return _problem_response(request, error)

    # Starlette runs `add_middleware`-registered middleware in REVERSE
    # registration order (last-added = outermost = first to run) -- so
    # `_TraceMiddleware` is added LAST here to make it the true outermost
    # layer (every request/response passes through it, including ones a
    # later-running middleware rejects).
    app.add_middleware(_TenantReconcileMiddleware)
    app.add_middleware(_TelemetryContextMiddleware)
    app.add_middleware(_TraceMiddleware)

    return app


__all__ = ["create_app"]

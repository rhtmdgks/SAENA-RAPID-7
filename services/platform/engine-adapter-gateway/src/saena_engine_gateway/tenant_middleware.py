"""Synchronous-HTTP tenant reconciliation middleware (ADR-0014).

Wraps `saena_domain.identity.http.reconcile_tenant` in a Starlette
`BaseHTTPMiddleware`: every request's `X-Saena-Tenant-Id` header is checked
against this pod's `SAENA_TENANT_ID` env var before the route handler runs.
A mismatch (or either side missing) is rejected with RFC 9457 403 —
ADR-0014 Constraints:64 forbids silently ignoring a mismatch or returning
200. `GET /v1/preflight` is exempt (it is the gateway's own self-check
endpoint, invoked by forgectl before any tenant context exists — k3s spec
§8.1).

On success, the reconciled `tenant_id` is bound onto
`saena_observability.context.bind_telemetry_context` (context="tenant") for
the duration of the request, so structured logs emitted while handling the
request automatically carry `saena.tenant_id` per ADR-0016 — this is the
"tenant-safe logging" wiring the task spec asks for.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from saena_domain.identity.errors import TenantMismatchError
from saena_domain.identity.http import TENANT_ENV_VAR_NAME, TENANT_HEADER_NAME, reconcile_tenant
from saena_observability.context import bind_telemetry_context
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

#: Endpoints reachable before/without an established tenant context — the
#: gateway's own operational self-check (k3s spec §8.1 preflight) and the
#: enum-bound engine listing, which is intentionally tenant-agnostic
#: metadata (no tenant-scoped data is returned).
_TENANT_EXEMPT_PATHS: frozenset[str] = frozenset({"/v1/preflight", "/v1/engines"})


class TenantReconciliationMiddleware(BaseHTTPMiddleware):
    """ADR-0014 synchronous HTTP tenant-reconciliation guard."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in _TENANT_EXEMPT_PATHS:
            return await call_next(request)

        header_value = request.headers.get(TENANT_HEADER_NAME)
        env_value = os.environ.get(TENANT_ENV_VAR_NAME)
        try:
            tenant_id = reconcile_tenant(header_value, env_value)
        except TenantMismatchError as exc:
            body = _mismatch_problem_detail(exc, instance=str(request.url.path))
            return JSONResponse(body, status_code=403, media_type="application/problem+json")

        with bind_telemetry_context("tenant", tenant_id=tenant_id):
            return await call_next(request)


def _mismatch_problem_detail(exc: TenantMismatchError, *, instance: str) -> dict[str, object]:
    """Shape a `TenantMismatchError` (a `saena_domain.identity` error, not
    an `EngineGatewayError`) into the same RFC 9457 body shape
    `build_problem_detail` produces, without importing a domain-package
    type into `saena_engine_gateway.errors` (that module stays free of any
    dependency beyond stdlib, per the exclusive-write-path/no-cross-import
    discipline this patch unit operates under).
    """
    from saena_observability.trace import current_trace_id, generate_trace_id

    trace_id = current_trace_id() or generate_trace_id()
    return {
        "type": "https://schemas.the-saena.ai/errors/identity/saena.identity.tenant_mismatch",
        "title": "TenantMismatchError",
        "status": 403,
        "detail": str(exc),
        "instance": instance,
        "error_code": exc.error_code,
        "retryable": False,
        "trace_id": trace_id,
    }

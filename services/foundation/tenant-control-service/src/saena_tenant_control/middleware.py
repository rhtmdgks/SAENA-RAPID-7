"""`X-Saena-Tenant-Id` <-> `SAENA_TENANT_ID` reconciliation middleware
(ADR-0014).

Wraps `saena_domain.identity.http.reconcile_tenant` (the domain-layer
comparison primitive) with the services-layer concerns that module's own
docstring explicitly defers: mapping a mismatch to an HTTP 403 response and
emitting a tenant-safe structured log record (ADR-0014 Constraints:64 —
"mismatch를 조용히 무시하거나 200으로 처리하는 코드 경로 금지"; publishing an
actual audit EVENT is out of scope here — see `service.py` module docstring
"why no `tenant.policy.updated.v1`" note, the same reasoning applies: this
service does not publish to a not-yet-CONFIRMED topic, and the audit-ledger
service, not tenant-control, owns the `AuditEvent` write path).

Only applied to tenant-scoped routes (`/v1/tenants/{tenant_id}...`) via
`TENANT_SCOPED_PATH_PREFIX` — the middleware is a no-op for any other path
(e.g. `/health`), matching ADR-0014's scope (it governs the synchronous HTTP
path for tenant-scoped calls, not every route a service exposes).

**Why route-logic exceptions are also caught here, not in a separate
`@app.exception_handler`**: `starlette.middleware.base.BaseHTTPMiddleware`
sits ABOVE `ExceptionMiddleware` in the ASGI stack (this is documented
Starlette behavior, not a bug) — an exception raised inside a route handler
propagates back up through this middleware's own `call_next(request)` call
BEFORE any FastAPI-registered `@app.exception_handler` would ever see it,
since those handlers run inside `ExceptionMiddleware`, which this middleware
wraps. A `try/except` purely around the `reconcile_tenant` call above would
therefore leave every route-handler exception (domain errors, unexpected
exceptions) unhandled by the time it reaches this middleware. This module
resolves that by catching broadly around `call_next(request)` for
tenant-scoped routes and routing every exception through
`errors.to_problem_detail` — the single problem-detail mapping point for
this service (`/health`, the only route outside `TENANT_SCOPED_PATH_PREFIX`,
raises nothing and needs no such handler).
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Final

from saena_domain.identity import TENANT_ENV_VAR_NAME, TENANT_HEADER_NAME, TenantMismatchError
from saena_domain.identity import reconcile_tenant as _reconcile_tenant
from saena_observability import get_logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from saena_tenant_control.errors import (
    TenantMismatchProblem,
    to_problem_detail,
    trace_id_for_request,
)

_logger = get_logger("saena_tenant_control.middleware")

#: Only routes under this prefix are tenant-scoped (ADR-0014 synchronous HTTP
#: path applies to tenant-scoped calls; `/health` and friends are exempt).
TENANT_SCOPED_PATH_PREFIX: Final[str] = "/v1/tenants"

#: Request-state key this middleware publishes the reconciled tenant_id
#: under, for downstream route handlers/dependencies to read without
#: re-parsing the header.
RECONCILED_TENANT_STATE_KEY: Final[str] = "reconciled_tenant_id"


def _env_tenant_id() -> str | None:
    """Read the pod's `SAENA_TENANT_ID` env var fresh on every call (not
    cached at import time) so tests can vary it per-request via
    `monkeypatch`/`os.environ` without reloading this module."""
    return os.environ.get(TENANT_ENV_VAR_NAME)


def _problem_response(exc: Exception, *, request: Request) -> JSONResponse:
    """Shared exception -> `JSONResponse` conversion (see module docstring
    "Why route-logic exceptions are also caught here")."""
    trace_id = trace_id_for_request(request)
    status, problem = to_problem_detail(exc, instance=str(request.url.path), trace_id=trace_id)
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(mode="json", exclude_none=True),
        media_type="application/problem+json",
    )


class TenantReconciliationMiddleware(BaseHTTPMiddleware):
    """Reconcile `X-Saena-Tenant-Id` against `SAENA_TENANT_ID` for every
    tenant-scoped request (403 + tenant-safe log on mismatch), and map every
    exception raised downstream (reconciliation or route-handler) to an RFC
    9457 problem response — see module docstring for why both concerns live
    in this one middleware."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not request.url.path.startswith(TENANT_SCOPED_PATH_PREFIX):
            return await call_next(request)

        header_value = request.headers.get(TENANT_HEADER_NAME)
        env_value = _env_tenant_id()

        try:
            reconciled = _reconcile_tenant(header_value, env_value)
        except TenantMismatchError as exc:
            # Tenant-safe log: only the structured `.context` the domain
            # exception already scoped to header/env names + values, never
            # free text interpolation (ADR-0014 Constraints:64 "audit
            # payload에 기록" — this service records it via structured log
            # rather than a not-yet-CONFIRMED audit event, see module
            # docstring).
            _logger.warning(
                "tenant reconciliation failed for %s %s",
                request.method,
                request.url.path,
                extra={"saena_attributes": {"saena.error_code": exc.error_code, **exc.context}},
            )
            problem_error = TenantMismatchProblem(str(exc), context=exc.context)
            return _problem_response(problem_error, request=request)

        request.state.__setattr__(RECONCILED_TENANT_STATE_KEY, reconciled)

        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 - single funnel point, see module docstring
            _logger.exception("unhandled exception in tenant-control-service request")
            return _problem_response(exc, request=request)

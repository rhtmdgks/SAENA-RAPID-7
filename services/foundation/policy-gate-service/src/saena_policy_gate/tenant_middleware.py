"""Tenant header reconciliation middleware (ADR-0014, same pattern as
`saena_domain.identity.http.reconcile_tenant` — this module is the
services-layer HTTP wiring around that domain primitive: ADR-0014 leaves the
"map `TenantMismatchError` to an actual HTTP 403 + audit event" step to the
services layer, by that module's own docstring).

Every request except `/v1/health` (fail-closed health probing, task
instruction 4 — a client checking gate liveness must not itself need a
resolved tenant identity) must carry `X-Saena-Tenant-Id` matching this pod's
`SAENA_TENANT_ID` env var; a mismatch or missing value is rejected with 403
via the RFC 9457 problem mapper — never silently ignored or 200-ed
(ADR-0014 Constraints:64).
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from saena_domain.identity.errors import TenantMismatchError
from saena_domain.identity.http import TENANT_ENV_VAR_NAME, TENANT_HEADER_NAME, reconcile_tenant
from starlette.middleware.base import BaseHTTPMiddleware

from saena_policy_gate.errors import TenantHeaderError
from saena_policy_gate.problem import build_problem, new_trace_id

_EXEMPT_PATHS = frozenset({"/v1/health"})


class TenantHeaderMiddleware(BaseHTTPMiddleware):
    """Reconciles `X-Saena-Tenant-Id` against `SAENA_TENANT_ID` and stashes
    the reconciled `tenant_id` on `request.state.tenant_id` for route
    handlers — never trusts the header alone without the env-var match.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        header_value = request.headers.get(TENANT_HEADER_NAME)
        env_value = os.environ.get(TENANT_ENV_VAR_NAME)
        try:
            tenant_id = reconcile_tenant(header_value, env_value)
        except TenantMismatchError as exc:
            gate_exc = TenantHeaderError(str(exc), context=exc.context)
            problem = build_problem(gate_exc, instance=str(request.url), trace_id=new_trace_id())
            return JSONResponse(
                status_code=gate_exc.http_status,
                content=problem,
                media_type="application/problem+json",
            )

        request.state.tenant_id = tenant_id
        return await call_next(request)


__all__ = ["TenantHeaderMiddleware"]

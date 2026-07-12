"""`X-Saena-Tenant-Id` <-> pod env `SAENA_TENANT_ID` reconciliation
middleware (ADR-0014 synchronous HTTP propagation path).

Wraps `saena_domain.identity.reconcile_tenant` (the domain-layer comparison
primitive) with the services-layer concerns that primitive's own docstring
explicitly defers: mapping a mismatch to HTTP 403 and emitting an
audit-shaped structured log record (ADR-0014 Constraints:64 — "mismatch를
조용히 무시하거나 200으로 처리하는 코드 경로 금지"; full append to the audit
ledger is out of scope for this patch unit, which has no `AuditLedgerPort`
wired in — the log record IS the audit-shaped artifact this unit produces,
carrying every field `saena_domain.identity.errors.TenantMismatchError.
context` exposes).

Requests with NO `X-Saena-Tenant-Id` header at all are treated as
tenant-agnostic (e.g. `GET /v1/actor/whoami`, health checks) and skip
reconciliation entirely — only a PRESENT-but-mismatched header (or a header
present while the pod env is unset, which ADR-0014's own primitive already
treats as a reconciliation failure) triggers the 403 path. This lets
non-tenant-scoped routes exist on the same app without forcing every caller
to send a header a health check has no use for.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from saena_domain.identity import TENANT_ENV_VAR_NAME, TENANT_HEADER_NAME
from saena_domain.identity.errors import TenantMismatchError
from saena_domain.identity.http import reconcile_tenant
from saena_observability import get_logger

from saena_forge_console.errors import ErrorCategory, ServiceError, to_problem_detail
from saena_forge_console.trace import resolve_trace_id

_logger = get_logger("saena_forge_console.tenant_reconcile")

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


async def tenant_reconciliation_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    header_value = request.headers.get(TENANT_HEADER_NAME)
    if header_value is None:
        return await call_next(request)

    env_value = os.environ.get(TENANT_ENV_VAR_NAME)
    try:
        reconcile_tenant(header_value, env_value)
    except TenantMismatchError as exc:
        trace_id = resolve_trace_id(request)
        # `header_value`/`env_value`/`error_code` are carried in the
        # free-text `body` message, not as `saena.*` structured attributes:
        # none of the three is a registered entry in the ADR-0016 attribute
        # registry (`packages/observability/registry/attributes.json`,
        # owned exclusively by `packages/observability` — CLAUDE.md
        # single-owner principle #7, out of this patch unit's write scope),
        # so passing them via `extra={"saena_attributes": ...}` would be
        # silently DROPPED by `SaenaJsonFormatter`'s allowlist-first
        # redaction rather than raise — `body` has no such allowlist gate.
        _logger.warning(
            "tenant reconciliation mismatch: error_code=%s header_value=%r env_value=%r",
            exc.error_code,
            exc.context.get("header_value"),
            exc.context.get("env_value"),
        )
        error = ServiceError(
            category=ErrorCategory.POLICY_DENIED,
            reason="tenant_mismatch",
            detail="X-Saena-Tenant-Id does not match this pod's tenant scope",
        )
        problem = to_problem_detail(error, trace_id=trace_id, instance=str(request.url))
        return Response(
            content=problem.model_dump_json(exclude_none=True),
            status_code=error.status_code,
            media_type="application/problem+json",
        )
    return await call_next(request)


__all__ = ["tenant_reconciliation_middleware"]

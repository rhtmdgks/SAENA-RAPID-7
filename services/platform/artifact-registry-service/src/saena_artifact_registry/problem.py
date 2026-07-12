"""RFC 9457 `application/problem+json` error mapping (ADR-0015).

Builds `saena_schemas.common.problem_detail_v1.ProblemDetail` (the generated
contract model — codegen only, `packages/schemas` is DO-NOT-EDIT) from any
`saena_artifact_registry.errors.ArtifactRegistryError`, and renders it as a
`fastapi.responses.JSONResponse` with the `application/problem+json` media
type.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from saena_observability.trace import current_trace_id, generate_trace_id
from saena_schemas.common.problem_detail_v1 import ProblemDetail

from saena_artifact_registry.errors import ArtifactRegistryError

_TYPE_BASE = "https://schemas.the-saena.ai/errors"


def _category_and_reason(error_code: str) -> tuple[str, str]:
    _, category, reason = error_code.split(".", 2)
    return category, reason


def build_problem_detail(
    error: ArtifactRegistryError,
    *,
    instance: str | None = None,
    tenant_id: str | None = None,
) -> ProblemDetail:
    """Build a `ProblemDetail` from `error` (ADR-0015 9-category taxonomy).

    `detail` carries only `str(error)` — callers MUST ensure error messages
    never embed blob content or raw manifest bytes (customer-proprietary
    MAX sensitivity); every error type in `errors.py` is constructed with a
    structural, content-free message for exactly this reason.
    """
    category, reason = _category_and_reason(error.error_code)
    trace_id = current_trace_id() or generate_trace_id()
    return ProblemDetail(
        type=f"{_TYPE_BASE}/{category}/{reason}",  # type: ignore[arg-type]
        title=type(error).__name__,
        status=error.status_code,
        detail=str(error),
        instance=instance,
        error_code=error.error_code,
        retryable=error.retryable,
        trace_id=trace_id,
        tenant_id=tenant_id,  # type: ignore[arg-type]
        run_id=None,
    )


def problem_response(
    error: ArtifactRegistryError,
    *,
    instance: str | None = None,
    tenant_id: str | None = None,
) -> JSONResponse:
    """Render `error` as an `application/problem+json` response."""
    problem = build_problem_detail(error, instance=instance, tenant_id=tenant_id)
    body: dict[str, Any] = problem.model_dump(mode="json", exclude_none=True)
    return JSONResponse(
        status_code=error.status_code,
        content=body,
        media_type="application/problem+json",
    )


async def artifact_registry_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI exception handler for `ArtifactRegistryError` and subclasses.

    Registered against `ArtifactRegistryError` (see `app.py`'s
    `add_exception_handler` call) — FastAPI guarantees `exc` is always an
    instance of that type at this call site.
    """
    if not isinstance(exc, ArtifactRegistryError):
        raise TypeError(f"unexpected exception type routed to this handler: {type(exc)!r}")
    tenant_id = getattr(request.state, "tenant_id", None)
    return problem_response(exc, instance=str(request.url.path), tenant_id=tenant_id)


__all__ = [
    "artifact_registry_error_handler",
    "build_problem_detail",
    "problem_response",
]

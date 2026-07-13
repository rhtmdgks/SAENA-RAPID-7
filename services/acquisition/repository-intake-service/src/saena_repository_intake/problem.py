"""RFC 9457 `application/problem+json` error mapping (ADR-0015) —
verbatim-pattern port of `saena_artifact_registry.problem` for
`saena_repository_intake`.

Builds `saena_schemas.common.problem_detail_v1.ProblemDetail` from any
`saena_repository_intake.errors.RepositoryIntakeError`. Also closes the same
two leak paths FastAPI's OWN defaults would otherwise open (critic MUST-FIX
w2-16 review, same rationale applies verbatim here — see
`saena_artifact_registry.problem`'s module docstring for the full write-up):
FastAPI's default 422 handler echoes the raw request body back to the
caller (this service's request body never carries source content — only
snapshot references — but the same discipline is cheap to keep, and future
fields are not guaranteed content-free forever), and an unmapped `Exception`
must never leak a stack trace.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from saena_observability.logging import get_logger
from saena_observability.trace import current_trace_id, generate_trace_id
from saena_schemas.common.problem_detail_v1 import ProblemDetail

from saena_repository_intake.errors import RepositoryIntakeError

_TYPE_BASE = "https://schemas.the-saena.ai/errors"
_logger = get_logger("saena_repository_intake")


def _category_and_reason(error_code: str) -> tuple[str, str]:
    _, category, reason = error_code.split(".", 2)
    return category, reason


def build_problem_detail(
    error: RepositoryIntakeError,
    *,
    instance: str | None = None,
    tenant_id: str | None = None,
) -> ProblemDetail:
    """Build a `ProblemDetail` from `error`. `detail` carries only
    `str(error)` — every `RepositoryIntakeError` subclass is constructed
    with a structural, content-free message (never a raw secret finding or
    source content, see `errors.py`'s own docstring)."""
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
    error: RepositoryIntakeError,
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


async def repository_intake_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI exception handler for `RepositoryIntakeError` and subclasses."""
    if not isinstance(exc, RepositoryIntakeError):
        raise TypeError(f"unexpected exception type routed to this handler: {type(exc)!r}")
    tenant_id = getattr(request.state, "tenant_id", None)
    return problem_response(exc, instance=str(request.url.path), tenant_id=tenant_id)


def _raw_problem_response(
    *,
    status_code: int,
    error_code: str,
    detail: str,
    instance: str | None,
    tenant_id: str | None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    category, reason = _category_and_reason(error_code)
    trace_id = current_trace_id() or generate_trace_id()
    problem = ProblemDetail(
        type=f"{_TYPE_BASE}/{category}/{reason}",  # type: ignore[arg-type]
        title=category.replace("_", " ").title(),
        status=status_code,
        detail=detail,
        instance=instance,
        error_code=error_code,
        retryable=False,
        trace_id=trace_id,
        tenant_id=tenant_id,  # type: ignore[arg-type]
        run_id=None,
    )
    body: dict[str, Any] = problem.model_dump(mode="json", exclude_none=True)
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=status_code, content=body, media_type="application/problem+json"
    )


async def request_validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI exception handler for `RequestValidationError` (422) —
    registered INSTEAD of FastAPI's default (never invoked); builds its own
    body from ONLY `loc`/`type`/`msg` per error, never `input`/`ctx`/`url`
    (see `saena_artifact_registry.problem.request_validation_error_handler`
    for the full leak-path rationale this mirrors)."""
    if not isinstance(exc, RequestValidationError):
        raise TypeError(f"unexpected exception type routed to this handler: {type(exc)!r}")
    tenant_id = getattr(request.state, "tenant_id", None)
    sanitized_errors = [
        {
            "loc": [str(part) for part in error.get("loc", ())],
            "type": error.get("type"),
            "msg": error.get("msg"),
        }
        for error in exc.errors()
    ]
    _logger.info(
        "request validation failed",
        extra={
            "saena_attributes": {
                "repository_intake.validation_error_count": len(sanitized_errors),
            }
        },
    )
    return _raw_problem_response(
        status_code=422,
        error_code="saena.validation.request_body_invalid",
        detail="request body failed schema validation",
        instance=str(request.url.path),
        tenant_id=tenant_id,
        extra={"errors": sanitized_errors},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Generic fallback — never a stack trace / exception message in the
    response; only the exception TYPE NAME is logged."""
    tenant_id = getattr(request.state, "tenant_id", None)
    response = _raw_problem_response(
        status_code=500,
        error_code="saena.internal.unexpected",
        detail="an unexpected error occurred",
        instance=str(request.url.path),
        tenant_id=tenant_id,
    )
    _logger.info(
        "unhandled exception",
        extra={
            "saena_attributes": {
                "repository_intake.exception_type": type(exc).__name__,
            }
        },
    )
    return response


__all__ = [
    "build_problem_detail",
    "problem_response",
    "repository_intake_error_handler",
    "request_validation_error_handler",
    "unhandled_exception_handler",
]

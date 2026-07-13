"""RFC 9457 `application/problem+json` error mapping (ADR-0015).

Builds `saena_schemas.common.problem_detail_v1.ProblemDetail` (the generated
contract model — codegen only, `packages/schemas` is DO-NOT-EDIT) from any
`saena_artifact_registry.errors.ArtifactRegistryError`, and renders it as a
`fastapi.responses.JSONResponse` with the `application/problem+json` media
type.

Two additional handlers close a leak path FastAPI's OWN defaults would
otherwise open (critic MUST-FIX, w2-16 review):

- `request_validation_error_handler` — FastAPI's default 422 response
  echoes the raw request body (`RequestValidationError.errors()[i]["input"]`)
  back to the caller. For `POST /v1/artifacts`, that body carries
  `blob_base64` — customer-source diff content at MAX sensitivity
  (contract-catalog.md PatchArtifact row "diff=소스"). This handler NEVER
  calls FastAPI's default handler; it builds its own `application/
  problem+json` body containing only `loc`/`type`/`msg` per error —
  `input`/`ctx`/`url` (which pydantic-core's `ErrorDetails` also carries and
  which can itself embed the offending value) are structurally stripped,
  never read.
- `unhandled_exception_handler` — a generic `Exception` (bug, adapter
  failure not already mapped to an `ArtifactRegistryError`) must not leak a
  stack trace / exception message (which could itself quote request data)
  to the client. Maps to a fixed-detail RFC 9457 500.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from saena_observability.logging import get_logger
from saena_observability.trace import current_trace_id, generate_trace_id
from saena_schemas.common.problem_detail_v1 import ProblemDetail

from saena_artifact_registry.errors import ArtifactRegistryError

_TYPE_BASE = "https://schemas.the-saena.ai/errors"
_logger = get_logger("saena_artifact_registry")


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


def _raw_problem_response(
    *,
    status_code: int,
    error_code: str,
    detail: str,
    instance: str | None,
    tenant_id: str | None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build a `ProblemDetail`-shaped response WITHOUT an
    `ArtifactRegistryError` instance — used by handlers for exception types
    this service does not itself raise (`RequestValidationError`, bare
    `Exception`)."""
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
    """FastAPI exception handler for `RequestValidationError` (422).

    FastAPI's DEFAULT 422 handler echoes `error["input"]` (the raw offending
    value from the request body) back to the client — for
    `POST /v1/artifacts`, that body carries `blob_base64` (customer-source
    diff content, MAX sensitivity). This handler is registered INSTEAD of
    that default (see `app.py`'s `add_exception_handler(RequestValidationError,
    ...)` call, which fully replaces FastAPI's built-in handler for this
    exception type — the default is never invoked) and builds its own body
    from ONLY `loc` + `type` + `msg` per error: `input`/`ctx`/`url` (which
    pydantic-core's `ErrorDetails` also carries, and which can itself embed
    the offending field value or a snippet of it) are never read, not even
    to log them — see `test_error_leak_prevention.py`'s "sentinel absent
    from response AND logs" assertions.
    """
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
                "artifact_registry.validation_error_count": len(sanitized_errors),
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
    """Generic fallback for any exception not already mapped to an
    `ArtifactRegistryError`/`RequestValidationError` (critic SHOULD-FIX,
    w2-16 review).

    Never includes a stack trace or `str(exc)` in the response — an
    unexpected exception's message could itself quote request data (e.g. a
    body-parsing failure deep in a dependency). Only a fixed detail string
    and `trace_id` are returned; the exception TYPE NAME (never its message)
    is logged for operator diagnosis.
    """
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
                "artifact_registry.exception_type": type(exc).__name__,
            }
        },
    )
    return response


__all__ = [
    "artifact_registry_error_handler",
    "build_problem_detail",
    "problem_response",
    "request_validation_error_handler",
    "unhandled_exception_handler",
]

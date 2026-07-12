"""RFC 9457 `application/problem+json` error responses (ADR-0015).

`saena_domain` exceptions (`ForbiddenAuditDataError`, `saena_domain.identity`/
`saena_domain.persistence` errors) already carry a `saena.<category>.<reason>`
`error_code` plus a structured, log-safe `context` dict where that base class
provides one — `ForbiddenAuditDataError` is a bare `ValueError` subclass with
no such base, so it is mapped explicitly below rather than duck-typed. This
module turns either shape into a `ProblemDetail`-shaped JSON body (the
generated `saena_schemas.common.problem_detail_v1.ProblemDetail` model) and a
matching HTTP status.

Guard-rail this module exists to enforce: `ForbiddenAuditDataError.reason`/
`.key_path` are safe to echo (see `saena_domain.audit.guard`'s own docstring —
the whole point of that guard is it never carries the offending value), but
this module still never interpolates a raw request body or any other
caller-supplied value into a `detail` string beyond what the domain-layer
exception itself already decided was safe to expose.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from saena_domain.audit import ForbiddenAuditDataError
from saena_domain.identity.errors import IdentityError
from saena_domain.persistence.errors import PersistenceError
from saena_observability import current_trace_id, generate_trace_id

PROBLEM_TYPE_BASE = "https://schemas.the-saena.ai/errors"
_MEDIA_TYPE = "application/problem+json"


def _trace_id() -> str:
    """The current OTel trace_id if bound, else a freshly generated one.

    A `ProblemDetail` response always carries a `trace_id` (required field,
    ADR-0015) even when no span is active for this request (e.g. a very
    early validation failure) — falling back to `generate_trace_id()` rather
    than emitting a malformed/absent value.
    """
    return current_trace_id() or generate_trace_id()


def problem_response(
    *,
    status: int,
    title: str,
    error_code: str,
    detail: str | None = None,
    retryable: bool = False,
    request: Request | None = None,
) -> JSONResponse:
    """Build a `JSONResponse` carrying a `ProblemDetail`-shaped body.

    `instance` is set from `request.url.path` when a `Request` is supplied
    (the concrete instance the error occurred on) — never a query string or
    body content, to avoid echoing caller-supplied values into the error
    body beyond the path itself.
    """
    body: dict[str, Any] = {
        "type": f"{PROBLEM_TYPE_BASE}/{error_code.replace('.', '/')}",
        "title": title,
        "status": status,
        "error_code": error_code,
        "retryable": retryable,
        "trace_id": _trace_id(),
    }
    if detail is not None:
        body["detail"] = detail
    if request is not None:
        body["instance"] = request.url.path
    return JSONResponse(status_code=status, content=body, media_type=_MEDIA_TYPE)


def forbidden_audit_data_problem(
    error: ForbiddenAuditDataError, *, request: Request | None = None
) -> JSONResponse:
    """Map `ForbiddenAuditDataError` to a 422 problem+json response.

    `error.key_path`/`error.reason` are safe to echo (see module docstring):
    the guard that raises this exception never puts the offending VALUE into
    either attribute, only the key path and a category label — so this is
    the one place in this module that does echo exception detail directly,
    because the domain layer has already made it safe to do so.
    """
    return problem_response(
        status=422,
        title="Forbidden audit data",
        error_code="saena.audit_ledger.forbidden_payload_data",
        detail=f"rejected at '{error.key_path}': {error.reason}",
        retryable=False,
        request=request,
    )


def domain_error_problem(
    error: IdentityError | PersistenceError, *, status: int, request: Request | None = None
) -> JSONResponse:
    """Map a `saena_domain` structured exception (`.error_code` + `.context`
    base classes) to a problem+json response at the given `status`."""
    return problem_response(
        status=status,
        title=type(error).__name__,
        error_code=error.error_code,
        detail=str(error),
        retryable=False,
        request=request,
    )


def not_found_problem(
    *, error_code: str, detail: str, request: Request | None = None
) -> JSONResponse:
    return problem_response(
        status=404,
        title="Not found",
        error_code=error_code,
        detail=detail,
        retryable=False,
        request=request,
    )


def bad_request_problem(
    *, error_code: str, detail: str, request: Request | None = None
) -> JSONResponse:
    return problem_response(
        status=400,
        title="Bad request",
        error_code=error_code,
        detail=detail,
        retryable=False,
        request=request,
    )


def forbidden_rbac_problem(*, permission: str, request: Request | None = None) -> JSONResponse:
    return problem_response(
        status=403,
        title="Forbidden",
        error_code="saena.audit_ledger.rbac_denied",
        detail=f"caller's roles do not grant permission '{permission}'",
        retryable=False,
        request=request,
    )

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

Value-echo hardening (critic MUST-FIX 1, w2-10 review): FastAPI's DEFAULT
`RequestValidationError` handler (and any bare pydantic `ValidationError`
this service's own code re-raises as a plain `str(exc)`, e.g. `AuditEntry`
re-validation inside `build_entry`) embeds the RAW caller-supplied value
verbatim in each error dict's `input` field / in `ValidationError.__str__`'s
`input_value=...` fragment — a wrong-type or malformed field value (which
could itself be a secret/PII/stack-trace fragment the caller mistakenly
pasted into the wrong field) is echoed straight back in the 422 body, and at
`application/json` content-type rather than this service's
`application/problem+json` convention. `safe_validation_errors` below is the
single choke point every validation-error-to-response path in this module
must go through: it keeps only `type`/`loc`/`msg` from each pydantic error
dict, dropping `input`/`url`/`ctx` (`ctx` can itself embed the rejected value
inside a nested `error`/`pattern` sub-field depending on the validator, so it
is dropped wholesale rather than allow-listed further).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from saena_domain.audit import ForbiddenAuditDataError
from saena_domain.identity.errors import IdentityError
from saena_domain.persistence.errors import PersistenceError
from saena_observability import current_trace_id, generate_trace_id

PROBLEM_TYPE_BASE = "https://schemas.the-saena.ai/errors"
_MEDIA_TYPE = "application/problem+json"

#: The only pydantic per-error dict keys ever surfaced to a caller — see
#: module docstring "Value-echo hardening". `input`/`url`/`ctx` are always
#: stripped, regardless of validator kind.
_SAFE_ERROR_KEYS = ("type", "loc", "msg")


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
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build a `JSONResponse` carrying a `ProblemDetail`-shaped body.

    `instance` is set from `request.url.path` when a `Request` is supplied
    (the concrete instance the error occurred on) — never a query string or
    body content, to avoid echoing caller-supplied values into the error
    body beyond the path itself. `extra` merges additional SAENA-extension
    fields beyond the `ProblemDetail` contract's own set (e.g.
    `validation_error_problem`'s `errors` list) — callers passing `extra`
    are responsible for ensuring its values are already value-safe (this
    function does not itself redact `extra`'s contents).
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
    if extra:
        body.update(extra)
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


def safe_validation_errors(raw_errors: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Strip every pydantic per-error dict down to `type`/`loc`/`msg`.

    `loc` is a tuple of path segments (field names / indices) — never the
    VALUE at that path — so it is always safe to echo; `type`/`msg` name the
    validator and a fixed, value-free message template. See module docstring
    "Value-echo hardening" for why `input`/`url`/`ctx` must never reach a
    caller. `loc` tuples are converted to lists for JSON-serialization
    (`jsonable_encoder` would do this too, but this module's own
    `problem_response` uses plain `JSONResponse`, which does not run
    `jsonable_encoder`).
    """
    return [
        {
            key: (list(value) if key == "loc" else value)
            for key, value in error.items()
            if key in _SAFE_ERROR_KEYS
        }
        for error in raw_errors
    ]


def validation_error_problem(
    error: RequestValidationError | ValidationError, *, request: Request | None = None
) -> JSONResponse:
    """Map a pydantic/FastAPI validation error to a 422 problem+json response.

    Never includes the raw caller-supplied value: `detail` carries only the
    value-free `safe_validation_errors` summary (critic MUST-FIX 1). Handles
    both `fastapi.exceptions.RequestValidationError` (raised by FastAPI's own
    request-body parsing, `.errors()` takes no filtering kwargs) and a bare
    `pydantic.ValidationError` (raised by e.g. `AuditEntry` re-validation
    inside `saena_domain.audit.build_entry`, whose `.errors()` DOES accept
    `include_input=False`/`include_url=False`/`include_context=False` — but
    this function calls `safe_validation_errors` uniformly on the raw dicts
    from either type rather than relying on that kwarg-level difference, so
    both paths get identical stripping behavior and neither can regress
    independently of the other).
    """
    errors = safe_validation_errors(error.errors())
    return problem_response(
        status=422,
        title="Validation error",
        error_code="saena.audit_ledger.validation_failed",
        detail="request failed validation; see 'errors' for field paths (values omitted)",
        retryable=False,
        request=request,
        extra={"errors": errors},
    )


def internal_error_problem(*, request: Request | None = None) -> JSONResponse:
    """Map an unexpected/unhandled exception to a 500 problem+json response.

    Never includes the exception's message, type, or a stack trace — an
    unhandled exception is, by definition, one this module has no structured,
    already-vetted-safe information about (contrast `domain_error_problem`,
    which only ever runs against `saena_domain` exceptions whose `.context`
    the domain layer itself already decided was log-safe).
    """
    return problem_response(
        status=500,
        title="Internal server error",
        error_code="saena.audit_ledger.internal_error",
        detail="an unexpected error occurred",
        retryable=True,
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

"""RFC 9457 `application/problem+json` error model (ADR-0015).

This module owns the ONE mapping point between (a) domain/persistence
exceptions raised by `saena_domain.identity`/`saena_domain.persistence` and
this service's own `TenantControlError` hierarchy, and (b) the wire-level
`ProblemDetail` body (`saena_schemas.common.problem_detail_v1.ProblemDetail`
— reused verbatim, no duplicate DTO). Every mapped response satisfies
ADR-0015's Constraints: no stack traces or raw exception text in `detail`
(only the exception's own `str()`, which every domain error in this repo
already keeps PII/secret-free by convention — see
`saena_domain.identity.errors`/`saena_domain.persistence.errors` module
docstrings), `policy_denied` never fails open, and `rate_limited` is unused
here (this service issues none).

`error_code` values already follow the `saena.<category>.<reason>` pattern
on every domain/persistence exception (`IdentityError`/`PersistenceError`
subclasses) — this module reuses them unchanged rather than inventing a
second vocabulary, exactly as those modules' docstrings anticipate.
"""

from __future__ import annotations

from typing import Any, Final

from saena_domain.identity.errors import (
    EngineScopeError,
    IdentityError,
    InvalidTenantIdError,
    TenantMismatchError,
    TenantSuspendedError,
)
from saena_domain.persistence.errors import NotFoundError, PersistenceError, TenantIsolationError
from saena_observability import generate_trace_id
from saena_schemas.common.problem_detail_v1 import ProblemDetail
from starlette.requests import Request

#: RFC 9457 `type` URI namespace (ADR-0015 "$id 스킴과 동형, non-resolvable").
_TYPE_BASE: Final[str] = "https://schemas.the-saena.ai/errors"


class TenantControlError(Exception):
    """Base class for errors raised directly by `saena_tenant_control` (as
    opposed to errors propagated from `saena_domain`).

    Same `error_code` + `context` shape as `saena_domain`'s own error
    hierarchies (`IdentityError`/`PersistenceError`) so `to_problem_detail`
    can treat every exception type uniformly.
    """

    error_code: str = "saena.internal.unexpected"
    status: int = 500
    retryable: bool = False
    title: str = "Internal error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}


class ValidationProblem(TenantControlError):
    """Request/contract validation failure (`validation` category)."""

    error_code = "saena.validation.schema_mismatch"
    status = 400
    retryable = False
    title = "Validation failed"


class NamespaceInputRejectedError(ValidationProblem):
    """A caller supplied `namespace` in a tenant-create request body.

    ADR-0014 Constraints:65 — `namespace` is a computed field, never an
    independent input. Distinct `error_code` from the generic validation
    category so clients can distinguish "you sent a namespace" from any
    other schema violation.
    """

    error_code = "saena.validation.namespace_input_rejected"
    title = "namespace is a computed field and must not be supplied"


class EngineScopeViolationProblem(TenantControlError):
    """Requested `engine_scope` includes an engine outside the v1 closed
    allow-list (`policy_denied` category — CLAUDE.md Engine scope v1)."""

    error_code = "saena.policy_denied.engine_scope_violation"
    status = 403
    retryable = False
    title = "Engine scope violation"


class TenantMismatchProblem(TenantControlError):
    """`X-Saena-Tenant-Id` header does not match the pod's `SAENA_TENANT_ID`
    env var, OR a path `tenant_id` does not match the reconciled tenant
    (ADR-0014 cross-tenant guard)."""

    error_code = "saena.auth.tenant_mismatch"
    status = 403
    retryable = False
    title = "Tenant mismatch"


class TenantSuspendedProblem(TenantControlError):
    """Gated read against a `suspended`/`terminating` tenant."""

    error_code = "saena.policy_denied.tenant_not_active"
    status = 403
    retryable = False
    title = "Tenant is not active"


class TenantAlreadyExistsProblem(TenantControlError):
    """`POST /v1/tenants` was called with a `tenant_id` already on record
    (`conflict` category — optimistic-lock-style state conflict)."""

    error_code = "saena.conflict.tenant_already_exists"
    status = 409
    retryable = False
    title = "Tenant already exists"


class InvalidStatusTransitionProblem(TenantControlError):
    """`POST /v1/tenants/{tenant_id}/status` requested a transition not in
    the allowed status state machine (`conflict` category)."""

    error_code = "saena.conflict.invalid_status_transition"
    status = 409
    retryable = False
    title = "Invalid tenant status transition"


class TenantNotFoundProblem(TenantControlError):
    """No tenant record exists for the given `tenant_id`."""

    error_code = "saena.not_found.resource_missing"
    status = 404
    retryable = False
    title = "Tenant not found"


# --- Mapping from saena_domain exceptions --------------------------------------------
#
# Every entry maps a `saena_domain` exception TYPE to (status, retryable,
# title) — `error_code` is read off the exception instance itself (already
# `saena.<category>.<reason>`, ADR-0015), never re-derived, so a new
# `saena_domain` error subclass automatically gets a correct `error_code`
# even before this table is updated (it will fall through to `_DEFAULT_*`
# for status/retryable/title until this table is extended, but the
# `error_code` on the wire is always the exception's own authoritative
# value).

_DOMAIN_ERROR_STATUS: Final[dict[type[Exception], tuple[int, bool, str]]] = {
    InvalidTenantIdError: (400, False, "Invalid tenant_id"),
    EngineScopeError: (403, False, "Engine scope violation"),
    TenantMismatchError: (403, False, "Tenant mismatch"),
    TenantSuspendedError: (403, False, "Tenant is not active"),
    NotFoundError: (404, False, "Resource not found"),
    TenantIsolationError: (403, False, "Cross-tenant access denied"),
}

_DEFAULT_STATUS = 500
_DEFAULT_RETRYABLE = False
_DEFAULT_TITLE = "Internal error"
_DEFAULT_ERROR_CODE = "saena.internal.unexpected"


def _category_from_error_code(error_code: str) -> str:
    """`saena.<category>.<reason>` -> `<category>` for the `type` URI."""
    parts = error_code.split(".")
    return parts[1] if len(parts) >= 2 else "internal"


def to_problem_detail(
    exc: Exception,
    *,
    instance: str,
    trace_id: str,
    tenant_id: str | None = None,
) -> tuple[int, ProblemDetail]:
    """Map any exception raised inside a request handler to `(status,
    ProblemDetail)`.

    Handles three exception families uniformly:

    1. `TenantControlError` (this module) — `error_code`/`status`/
       `retryable`/`title` are read directly off the exception's class
       attributes.
    2. `IdentityError`/`PersistenceError` (`saena_domain`) — `error_code` is
       read off the instance (already `saena.<category>.<reason>`);
       `status`/`retryable`/`title` come from `_DOMAIN_ERROR_STATUS`,
       defaulting to a fail-closed 500/non-retryable/"Internal error" for any
       type not in that table (never guessed as a permissive 2xx/4xx).
    3. Anything else (unexpected exception) — mapped to the `internal`
       category, 500, non-retryable, generic title/detail. `detail` NEVER
       includes `str(exc)` for this branch (that could be a raw stack-trace
       fragment or library-internal message never vetted against ADR-0015's
       PII/secret constraint) — only the fixed, safe string below.
    """
    if isinstance(exc, TenantControlError):
        error_code = exc.error_code
        status = exc.status
        retryable = exc.retryable
        title = exc.title
        detail: str | None = str(exc) or None
    elif isinstance(exc, IdentityError | PersistenceError):
        error_code = exc.error_code
        status, retryable, title = _DOMAIN_ERROR_STATUS.get(
            type(exc), (_DEFAULT_STATUS, _DEFAULT_RETRYABLE, _DEFAULT_TITLE)
        )
        detail = str(exc) or None
    else:
        error_code = _DEFAULT_ERROR_CODE
        status = _DEFAULT_STATUS
        retryable = _DEFAULT_RETRYABLE
        title = _DEFAULT_TITLE
        # No stack trace / exception text — ADR-0015 Constraints, "detail
        # 필드에 ... 원문 포함 금지" applied conservatively to unclassified
        # exceptions this module did not itself vet.
        detail = "An unexpected internal error occurred."

    category = _category_from_error_code(error_code)
    problem = ProblemDetail(
        type=f"{_TYPE_BASE}/{category}/{error_code.rsplit('.', 1)[-1]}",  # type: ignore[arg-type]
        title=title,
        status=status,
        detail=detail,
        instance=instance,
        error_code=error_code,
        retryable=retryable,
        trace_id=trace_id,
        tenant_id=tenant_id,  # type: ignore[arg-type]
    )
    return status, problem


def trace_id_for_request(request: Request) -> str:
    """A per-request 32-hex trace_id for problem-detail correlation.

    Shared by `middleware.py` and `app.py` — both need the same value shape
    for `to_problem_detail`'s `trace_id` argument. Reuses an inbound value
    already stashed on `request.state.trace_id` (a future tracing-middleware
    hook, not wired in W2A) when present; otherwise generates a fresh, valid
    (non-all-zero) trace_id via `saena_observability.generate_trace_id` —
    the same OTel-SDK-backed generator used everywhere else in this repo,
    rather than an ad hoc reformatting or an invalid all-zero placeholder.
    """
    existing = getattr(request.state, "trace_id", None)
    if isinstance(existing, str):
        return existing
    return generate_trace_id()

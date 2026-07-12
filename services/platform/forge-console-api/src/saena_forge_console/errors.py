"""RFC 9457 `application/problem+json` error model (ADR-0015).

`ServiceError` is this service's own exception type: every route/dependency
raises `ServiceError` (or a subclass), never a bare `HTTPException`, so a
single FastAPI exception handler (`saena_forge_console.app`) can map every
error path through one function — `to_problem_detail` — into a
schema-validated `saena_schemas.common.problem_detail_v1.ProblemDetail`
payload.

Field provenance (ADR-0015 "동기 API 에러 포맷" table):
    type      -- "https://schemas.the-saena.ai/errors/<category>/<reason>"
                 (ADR-0011 $id scheme, non-resolvable URI, ADR-0015:29).
    title     -- human-readable summary, derived from the category.
    status    -- HTTP status code for the category (below).
    detail    -- caller-supplied, PII/secret-free free text (ADR-0015
                 Constraints:70 — callers must never pass customer source,
                 secrets, or raw request bodies here).
    error_code-- `saena.<category>.<reason>` (ADR-0015 pattern), reused
                 verbatim from `saena_domain`'s own exception `error_code`
                 attributes where this service is wrapping a domain error.
    retryable -- per-category default (ADR-0015 taxonomy table), overridable
                 per raise site.
    trace_id  -- ADR-0013 envelope trace_id format (32-hex), always present
                 (services-layer trace binding, `saena_forge_console.trace`).
    tenant_id -- optional, present when the request already resolved a
                 tenant.
    run_id    -- optional, present when the request concerns a specific run.

`policy_denied` fail-closed note (ADR-0015 Constraints:71): this service does
not implement a policy gate itself (that is policy-gate-service's
responsibility, out of this patch unit's scope) — the category is defined
here only so this module's taxonomy stays complete/reusable if a future
route needs it; no route in this patch unit raises it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from saena_schemas.common.problem_detail_v1 import ProblemDetail

_TYPE_BASE = "https://schemas.the-saena.ai/errors"


class ErrorCategory(StrEnum):
    """ADR-0015 9-category taxonomy."""

    VALIDATION = "validation"
    AUTH = "auth"
    POLICY_DENIED = "policy_denied"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ENGINE = "upstream_engine"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


#: HTTP status + default retryable per category (ADR-0015 taxonomy table).
_CATEGORY_STATUS: dict[ErrorCategory, int] = {
    ErrorCategory.VALIDATION: 422,
    ErrorCategory.AUTH: 401,
    ErrorCategory.POLICY_DENIED: 403,
    ErrorCategory.CONFLICT: 409,
    ErrorCategory.NOT_FOUND: 404,
    ErrorCategory.RATE_LIMITED: 429,
    ErrorCategory.UPSTREAM_ENGINE: 502,
    ErrorCategory.UNAVAILABLE: 503,
    ErrorCategory.INTERNAL: 500,
}

_CATEGORY_RETRYABLE_DEFAULT: dict[ErrorCategory, bool] = {
    ErrorCategory.VALIDATION: False,
    ErrorCategory.AUTH: False,
    ErrorCategory.POLICY_DENIED: False,
    ErrorCategory.CONFLICT: False,
    ErrorCategory.NOT_FOUND: False,
    ErrorCategory.RATE_LIMITED: True,
    ErrorCategory.UPSTREAM_ENGINE: True,
    ErrorCategory.UNAVAILABLE: True,
    ErrorCategory.INTERNAL: False,
}

_CATEGORY_TITLE: dict[ErrorCategory, str] = {
    ErrorCategory.VALIDATION: "Request validation failed",
    ErrorCategory.AUTH: "Authentication failed",
    ErrorCategory.POLICY_DENIED: "Request denied by policy",
    ErrorCategory.CONFLICT: "Resource state conflict",
    ErrorCategory.NOT_FOUND: "Resource not found",
    ErrorCategory.RATE_LIMITED: "Rate limit exceeded",
    ErrorCategory.UPSTREAM_ENGINE: "Upstream engine failure",
    ErrorCategory.UNAVAILABLE: "Service unavailable",
    ErrorCategory.INTERNAL: "Internal error",
}


class ServiceError(Exception):
    """Base exception for every error this service's routes/dependencies
    raise. Carries everything `to_problem_detail` needs to build an RFC 9457
    body without re-deriving category/status/retryable at the handler site.
    """

    def __init__(
        self,
        category: ErrorCategory,
        reason: str,
        *,
        detail: str | None = None,
        tenant_id: str | None = None,
        run_id: str | None = None,
        retryable: bool | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.category = category
        self.reason = reason
        self.detail = detail
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.retryable = (
            retryable if retryable is not None else _CATEGORY_RETRYABLE_DEFAULT[category]
        )
        #: Extra response headers the handler must attach (e.g.
        #: `Retry-After` for `rate_limited`, ADR-0015 Constraints:73).
        self.headers = dict(headers) if headers is not None else {}
        super().__init__(f"{category.value}.{reason}: {detail or ''}")

    @property
    def error_code(self) -> str:
        return f"saena.{self.category.value}.{self.reason}"

    @property
    def status_code(self) -> int:
        return _CATEGORY_STATUS[self.category]


def validation_error(reason: str, *, detail: str | None = None) -> ServiceError:
    return ServiceError(ErrorCategory.VALIDATION, reason, detail=detail)


def auth_error(reason: str, *, detail: str | None = None) -> ServiceError:
    return ServiceError(ErrorCategory.AUTH, reason, detail=detail)


def policy_denied_error(
    reason: str, *, detail: str | None = None, tenant_id: str | None = None
) -> ServiceError:
    return ServiceError(ErrorCategory.POLICY_DENIED, reason, detail=detail, tenant_id=tenant_id)


def not_found_error(
    reason: str,
    *,
    detail: str | None = None,
    tenant_id: str | None = None,
    run_id: str | None = None,
) -> ServiceError:
    return ServiceError(
        ErrorCategory.NOT_FOUND, reason, detail=detail, tenant_id=tenant_id, run_id=run_id
    )


def internal_error(reason: str, *, detail: str | None = None) -> ServiceError:
    return ServiceError(ErrorCategory.INTERNAL, reason, detail=detail)


def to_problem_detail(error: ServiceError, *, trace_id: str, instance: str) -> ProblemDetail:
    """Build a schema-validated `ProblemDetail` from a `ServiceError`.

    `trace_id` and `instance` are always supplied by the caller (the
    exception handler) rather than read off `error`, since those two fields
    are per-request context the error object itself does not carry.
    """
    payload: dict[str, Any] = {
        "type": f"{_TYPE_BASE}/{error.category.value}/{error.reason}",
        "title": _CATEGORY_TITLE[error.category],
        "status": error.status_code,
        "error_code": error.error_code,
        "retryable": error.retryable,
        "trace_id": trace_id,
        "instance": instance,
    }
    if error.detail is not None:
        payload["detail"] = error.detail
    if error.tenant_id is not None:
        payload["tenant_id"] = error.tenant_id
    if error.run_id is not None:
        payload["run_id"] = error.run_id
    return ProblemDetail.model_validate(payload)


__all__ = [
    "ErrorCategory",
    "ServiceError",
    "auth_error",
    "internal_error",
    "not_found_error",
    "policy_denied_error",
    "to_problem_detail",
    "validation_error",
]

"""Exception hierarchy for `saena_site_discovery`.

Follows the same shape as `saena_artifact_registry.errors` /
`saena_domain.execution.errors`: every exception carries an `error_code`
(`saena.<category>.<reason>`, ADR-0015 taxonomy) and a structured, log-safe
`.context` dict. `to_job_error()` additionally renders the exception as a
`saena_domain.execution.job_error.JobError` value object (reusing the SAME
canonical error model the shared execution-domain layer defines, rather than
inventing a second one) — every `error_code` below is chosen so its category
segment is one of `JobError.KNOWN_ERROR_CATEGORIES`, so `to_job_error()`
never itself raises `JobErrorValidationError`.
"""

from __future__ import annotations

from typing import Any

from saena_domain.execution import JobError


class SiteDiscoveryError(Exception):
    """Base class for every error raised by `saena_site_discovery`."""

    error_code: str = "saena.internal.site_discovery_error"
    retryable: bool = False

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), **self.context}

    def to_job_error(self) -> JobError:
        """Render this exception as a canonical `JobError` (ADR-0015),
        truncated to `JobError`'s own 500-char summary bound."""
        return JobError(
            error_code=self.error_code,
            summary=str(self)[:500],
            retryable=self.retryable,
        )


class JobKindScopeError(SiteDiscoveryError):
    """A caller passed a `JobKind` other than `JobKind.SITE_DISCOVERY` to a
    function that exists to serve this one job kind only (defensive scope
    guard — mirrors `saena_domain.execution.engine.guard_engine_id`'s "is
    this even permitted at all" shape, applied to job-kind scope instead of
    engine-id scope)."""

    error_code = "saena.validation.job_kind_scope_invalid"


class CrawlBudgetExceededError(SiteDiscoveryError):
    """The number of routes requested for one discovery run exceeds this
    `JobKind`'s `ResourceLimits`-derived `CrawlBudget.max_routes_per_run`."""

    error_code = "saena.rate_limited.crawl_budget_exceeded"
    retryable = True


class CrawlDeadlineExceededError(SiteDiscoveryError):
    """Elapsed wall-clock time for one discovery run exceeded
    `ResourceLimits.active_deadline_seconds` before every requested route
    was processed."""

    error_code = "saena.rate_limited.crawl_deadline_exceeded"
    retryable = True


class CrawlRetryExhaustedError(SiteDiscoveryError):
    """A single route's fetch kept failing transiently past
    `ResourceLimits.max_retries`."""

    error_code = "saena.upstream_engine.crawl_retry_exhausted"
    retryable = True


class CrossTenantObservationError(SiteDiscoveryError):
    """A caller attempted to store or read a `SiteInventoryObservation`
    under a `tenant_id` different from the one it was captured under (fail
    closed — mirrors `saena_artifact_registry.blobstore.BlobStore`'s
    cross-tenant gating discipline)."""

    error_code = "saena.auth.cross_tenant_denied"


class SiteInventoryNotFoundError(SiteDiscoveryError):
    """No stored `SiteInventoryObservation` exists for the requested
    `(tenant_id, site_id)` key."""

    error_code = "saena.not_found.site_inventory"


__all__ = [
    "CrawlBudgetExceededError",
    "CrawlDeadlineExceededError",
    "CrawlRetryExhaustedError",
    "CrossTenantObservationError",
    "JobKindScopeError",
    "SiteDiscoveryError",
    "SiteInventoryNotFoundError",
]

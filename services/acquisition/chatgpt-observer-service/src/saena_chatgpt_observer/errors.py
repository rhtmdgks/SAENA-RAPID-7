"""Exception hierarchy for `saena_chatgpt_observer`.

Same shape as `saena_site_discovery.errors` (that module's docstring
applies verbatim here): `error_code`/`context`/`to_job_error()`, every
category chosen from `JobError.KNOWN_ERROR_CATEGORIES`. `engine_id` scope
rejection is NOT duplicated here — this package always calls
`saena_domain.execution.guard_engine_id` directly and lets its
`EngineNotPermittedError`/`EngineDisallowedError` propagate unchanged (see
`observation.py`), rather than wrapping it in a bespoke local exception
type.
"""

from __future__ import annotations

from typing import Any

from saena_domain.execution import JobError


class ChatgptObserverError(Exception):
    """Base class for every error raised by `saena_chatgpt_observer`."""

    error_code: str = "saena.internal.chatgpt_observer_error"
    retryable: bool = False

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), **self.context}

    def to_job_error(self) -> JobError:
        return JobError(
            error_code=self.error_code,
            summary=str(self)[:500],
            retryable=self.retryable,
        )


class JobKindScopeError(ChatgptObserverError):
    """A caller passed a `JobKind` other than `JobKind.CHATGPT_OBSERVER` to
    a function that exists to serve this one job kind only."""

    error_code = "saena.validation.job_kind_scope_invalid"


class ObservationBudgetExceededError(ChatgptObserverError):
    """The number of queries requested for one observation run exceeds this
    `JobKind`'s `ResourceLimits`-derived `ObservationBudget.max_queries_per_run`."""

    error_code = "saena.rate_limited.observation_budget_exceeded"
    retryable = True


class ObservationDeadlineExceededError(ChatgptObserverError):
    """Elapsed wall-clock time for one observation run exceeded
    `ResourceLimits.active_deadline_seconds` before every requested query
    was captured."""

    error_code = "saena.rate_limited.observation_deadline_exceeded"
    retryable = True


class ObservationRetryExhaustedError(ChatgptObserverError):
    """A single query's capture kept failing transiently past
    `ResourceLimits.max_retries`."""

    error_code = "saena.upstream_engine.observation_retry_exhausted"
    retryable = True


class CrossTenantObservationError(ChatgptObserverError):
    """A caller attempted to store or read a `PlatformObservation` under a
    `tenant_id` different from the one it was captured under (fail
    closed)."""

    error_code = "saena.auth.cross_tenant_denied"


class ObservationNotFoundError(ChatgptObserverError):
    """No stored `PlatformObservation` exists for the requested key."""

    error_code = "saena.not_found.platform_observation"


class BrowserPoolExhaustedError(ChatgptObserverError):
    """`BrowserPool.acquire()` timed out — every pooled session was in use
    and no new session could be created within `max_size` (w4-08 pool
    lifecycle "bounded size")."""

    error_code = "saena.rate_limited.browser_pool_exhausted"
    retryable = True


class BrowserPoolClosedError(ChatgptObserverError):
    """A caller attempted to `acquire()` from an already-`close()`d
    `BrowserPool`."""

    error_code = "saena.unavailable.browser_pool_closed"


class BrowserSessionRenderError(ChatgptObserverError):
    """A `BrowserSessionPort.render_search_result` call failed (fixture:
    unregistered query or a closed session; real driver: any Playwright/
    network failure — see `playwright_driver.py`)."""

    error_code = "saena.upstream_engine.browser_session_render_failed"
    retryable = True


__all__ = [
    "BrowserPoolClosedError",
    "BrowserPoolExhaustedError",
    "BrowserSessionRenderError",
    "ChatgptObserverError",
    "CrossTenantObservationError",
    "JobKindScopeError",
    "ObservationBudgetExceededError",
    "ObservationDeadlineExceededError",
    "ObservationNotFoundError",
    "ObservationRetryExhaustedError",
]

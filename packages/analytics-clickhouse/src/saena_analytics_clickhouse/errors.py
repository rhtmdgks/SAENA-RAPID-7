"""Exception hierarchy for `saena_analytics_clickhouse`.

Same shape as `saena_domain.persistence.errors` / `saena_chatgpt_observer.
errors` (`error_code` + structured, log-safe `context` dict) so a
services-layer problem-detail mapper can reuse these verbatim — see those
modules' own docstrings for the rationale. This package is deliberately
standalone (imports no other `saena_*` package, see `pyproject.toml`'s
Integrator note), so the hierarchy is redefined locally rather than
subclassing `saena_domain.persistence.errors.PersistenceError`.
"""

from __future__ import annotations

from typing import Any


class AnalyticsClickHouseError(Exception):
    """Base class for every error raised by `saena_analytics_clickhouse`."""

    error_code: str = "saena.analytics_clickhouse.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class RowValidationError(AnalyticsClickHouseError):
    """A row model field failed validation at construction time (e.g. missing
    `tenant_id`, malformed/naive `occurred_at`, empty `idempotency_key`)."""

    error_code = "saena.validation.analytics_row_invalid"


class RawContentRejectedError(AnalyticsClickHouseError):
    """A row carried an obviously-raw field (oversize blob / secret-shaped
    value / forbidden field name) — REJECTED fail-closed before it ever
    reaches a query builder or executor.

    The triggering VALUE is never included in `context` or the message —
    only the field NAME and a redacted reason, per data-ownership.md ("No
    PII/secrets in event payloads") and the mission's "redacted error"
    requirement. See `saena_analytics_clickhouse.guard`.
    """

    error_code = "saena.security.raw_content_rejected"


class TenantIsolationError(AnalyticsClickHouseError):
    """A caller attempted to write a row whose own `tenant_id` does not
    match the `tenant_id` it is being appended under, or attempted to
    construct a query without a `tenant_id` (data-ownership.md /
    tenancy-model.md — cross-tenant access target: 0)."""

    error_code = "saena.auth.cross_tenant_denied"


class UnknownTableError(AnalyticsClickHouseError):
    """A query/migration referenced a table this package does not own."""

    error_code = "saena.validation.unknown_analytics_table"


class MigrationError(AnalyticsClickHouseError):
    """A migration failed to apply (up) or reverse (down)."""

    error_code = "saena.analytics_clickhouse.migration_failed"


__all__ = [
    "AnalyticsClickHouseError",
    "MigrationError",
    "RawContentRejectedError",
    "RowValidationError",
    "TenantIsolationError",
    "UnknownTableError",
]

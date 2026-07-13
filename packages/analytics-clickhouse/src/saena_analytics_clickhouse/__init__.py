"""`saena_analytics_clickhouse` — ClickHouse analytical-store adapter +
migrations (w4-06, Wave 4).

Spec basis: ADR-0007 rev.2 §4-5, `docs/architecture/data-ownership.md`
(ClickHouse row), `docs/architecture/tenancy-model.md`/`security-model.md`.
See `README.md` for the table/partition/ORDER-BY inventory and the OPEN TTL
decision. This package is a standalone leaf — it imports no other `saena_*`
package (see `pyproject.toml`'s Integrator note).
"""

from __future__ import annotations

from saena_analytics_clickhouse.errors import (
    AnalyticsClickHouseError,
    MigrationError,
    RawContentRejectedError,
    RowValidationError,
    TenantIsolationError,
    UnknownTableError,
)
from saena_analytics_clickhouse.executor import (
    ClickHouseConnectExecutor,
    ClickHouseExecutor,
    ExecutorError,
    create_executor,
)
from saena_analytics_clickhouse.identifiers import TenantId
from saena_analytics_clickhouse.query import AnalyticsQuery, TenantScopedQuery
from saena_analytics_clickhouse.rows import CitationRow, ExperimentRegistrationRow, ObservationRow
from saena_analytics_clickhouse.schema import MIGRATIONS, TABLE_NAMES, migrate_down, migrate_up
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore

__all__ = [
    "MIGRATIONS",
    "TABLE_NAMES",
    "AnalyticsClickHouseError",
    "AnalyticsQuery",
    "CitationRow",
    "ClickHouseAnalyticsStore",
    "ClickHouseConnectExecutor",
    "ClickHouseExecutor",
    "ExecutorError",
    "ExperimentRegistrationRow",
    "MigrationError",
    "ObservationRow",
    "RawContentRejectedError",
    "RowValidationError",
    "TenantId",
    "TenantIsolationError",
    "TenantScopedQuery",
    "UnknownTableError",
    "create_executor",
    "migrate_down",
    "migrate_up",
]

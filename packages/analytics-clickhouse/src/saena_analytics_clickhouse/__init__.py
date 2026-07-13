"""`saena_analytics_clickhouse` — ClickHouse analytical-store adapter +
migrations (w4-06, Wave 4; query privacy boundary — r4-04, Wave 4
remediation).

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
from saena_analytics_clickhouse.query_privacy import (
    QUERY_SIGNING_KEY_ENV_VAR,
    MissingQuerySigningKeyError,
    QueryDigest,
    QueryRef,
    QuerySigningKeyRef,
    derive_query_digest,
    derive_query_ref,
)
from saena_analytics_clickhouse.rows import (
    MEASUREMENT_OUTCOME_B_VERDICTS,
    MEASUREMENT_OUTCOME_LAYERS,
    CitationRow,
    ExperimentRegistrationRow,
    MeasurementOutcomeRow,
    ObservationRow,
    RawVsAdjustedLiftRow,
)
from saena_analytics_clickhouse.schema import MIGRATIONS, TABLE_NAMES, migrate_down, migrate_up
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore

__all__ = [
    "MEASUREMENT_OUTCOME_B_VERDICTS",
    "MEASUREMENT_OUTCOME_LAYERS",
    "MIGRATIONS",
    "QUERY_SIGNING_KEY_ENV_VAR",
    "TABLE_NAMES",
    "AnalyticsClickHouseError",
    "AnalyticsQuery",
    "CitationRow",
    "ClickHouseAnalyticsStore",
    "ClickHouseConnectExecutor",
    "ClickHouseExecutor",
    "ExecutorError",
    "ExperimentRegistrationRow",
    "MeasurementOutcomeRow",
    "MigrationError",
    "MissingQuerySigningKeyError",
    "ObservationRow",
    "QueryDigest",
    "QueryRef",
    "QuerySigningKeyRef",
    "RawContentRejectedError",
    "RawVsAdjustedLiftRow",
    "RowValidationError",
    "TenantId",
    "TenantIsolationError",
    "TenantScopedQuery",
    "UnknownTableError",
    "create_executor",
    "derive_query_digest",
    "derive_query_ref",
    "migrate_down",
    "migrate_up",
]

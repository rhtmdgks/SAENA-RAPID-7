"""`ClickHouseAnalyticsStore` — the package's public adapter (w4-06 mission
deliverable 2).

Every QUERY method takes `tenant_id` as its first, non-defaulted positional
argument and routes exclusively through `query.AnalyticsQuery.for_tenant`
(never a hand-built WHERE clause) — see `query.py`'s module docstring for
why this makes an unscoped cross-tenant query structurally impossible to
construct, not merely discouraged by convention.

Every APPEND method is idempotent on `(tenant_id, idempotency_key)`: before
issuing an INSERT, `_append` runs an existence check
(`_exists_idempotency_key`) scoped to that exact pair; a duplicate call with
the same key is a no-op (returns `False`), never a second row or a raised
error — this is the mission's "duplicate-event idempotency" requirement.
Late/out-of-order tolerance falls out of this same design for free: an
`occurred_at` older than already-ingested rows is accepted unconditionally
(this store enforces no monotonicity constraint on `occurred_at` — only on
`idempotency_key` uniqueness), matching data-ownership.md/ADR-0007's
append-only, time-partitioned model where a late-arriving event simply lands
in its own OWN correct partition, never rejected for arriving "late".

This adapter never imports `clickhouse_connect` directly — every I/O call
goes through the injected `ClickHouseExecutor` (`executor.py`), so the exact
same adapter code path is exercised by the deterministic unit lane (in-memory
fake executor) and the real-container integration lane (`ClickHouseConnectExecutor`).
"""

from __future__ import annotations

from datetime import UTC, datetime

from saena_analytics_clickhouse.executor import ClickHouseExecutor
from saena_analytics_clickhouse.identifiers import validate_tenant_id
from saena_analytics_clickhouse.query import AnalyticsQuery, build_insert_columns
from saena_analytics_clickhouse.rows import CitationRow, ExperimentRegistrationRow, ObservationRow

# Column order matches `schema.py`'s CREATE TABLE DDL exactly (`tenant_id,
# id, idempotency_key, occurred_at, ingested_at, ...`) — this is also the
# exact positional order each `_*_from_values` unpacker below expects, so a
# `get_*` query's SELECT column list and a reconstructed row's field order
# never have to be reconciled by a separate reorder step.
_OBSERVATIONS_SELECT_COLUMNS: tuple[str, ...] = (
    "tenant_id",
    "id",
    "idempotency_key",
    "occurred_at",
    "ingested_at",
    "engine_id",
    "run_id",
    "query_text",
    "citation_refs",
    "raw_object_ref",
)

_CITATIONS_SELECT_COLUMNS: tuple[str, ...] = (
    "tenant_id",
    "id",
    "idempotency_key",
    "occurred_at",
    "ingested_at",
    "run_id",
    "observation_id",
    "citation_ref",
    "source_domain",
    "contribution_score",
)

_EXPERIMENT_REGISTRATIONS_SELECT_COLUMNS: tuple[str, ...] = (
    "tenant_id",
    "id",
    "idempotency_key",
    "occurred_at",
    "ingested_at",
    "engine_id",
    "locale",
    "observation_cell",
    "registration_hash",
    "status",
)


def _observation_fields(row: ObservationRow) -> dict[str, object]:
    return {
        "tenant_id": row.tenant_id,
        "id": row.id,
        "idempotency_key": row.idempotency_key,
        "occurred_at": row.occurred_at,
        "engine_id": row.engine_id,
        "run_id": row.run_id,
        "query_text": row.query_text,
        "citation_refs": list(row.citation_refs),
        "raw_object_ref": row.raw_object_ref,
    }


def _citation_fields(row: CitationRow) -> dict[str, object]:
    return {
        "tenant_id": row.tenant_id,
        "id": row.id,
        "idempotency_key": row.idempotency_key,
        "occurred_at": row.occurred_at,
        "run_id": row.run_id,
        "observation_id": row.observation_id,
        "citation_ref": row.citation_ref,
        "source_domain": row.source_domain,
        "contribution_score": row.contribution_score,
    }


def _experiment_registration_fields(row: ExperimentRegistrationRow) -> dict[str, object]:
    return {
        "tenant_id": row.tenant_id,
        "id": row.id,
        "idempotency_key": row.idempotency_key,
        "occurred_at": row.occurred_at,
        "engine_id": row.engine_id,
        "locale": row.locale,
        "observation_cell": row.observation_cell,
        "registration_hash": row.registration_hash,
        "status": row.status,
    }


def _coerce_utc(value: object) -> datetime | None:
    """Reattach `tzinfo=UTC` to a NAIVE `datetime` returned by a real
    ClickHouse driver.

    ClickHouse's `DateTime64(3, 'UTC')` column type (`schema.py`) guarantees
    every stored instant is ALREADY unambiguous UTC — but `clickhouse-connect`
    (and most ClickHouse Python drivers) hand back a naive `datetime.datetime`
    from a query result regardless (the timezone is a SERVER-side storage/
    display concept, not carried in the Python value the driver constructs).
    `rows.py`'s `validate_utc_datetime` rejects naive datetimes outright
    (correctness guard against a caller passing an AMBIGUOUS timestamp at
    construction time) — this coercion is the one place in this package that
    re-attaches UTC to a value this package's OWN schema already guarantees
    is UTC, so a real round-trip through a live ClickHouse table does not
    spuriously fail that same guard. The deterministic unit lane's
    `FakeClickHouseExecutor` stores/returns whatever `datetime` object it was
    given verbatim (already UTC-aware, since `rows.py` never let a naive one
    in), so this is a no-op there.
    """
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value  # type: ignore[return-value]


def _observation_from_values(values: tuple[object, ...]) -> ObservationRow:
    (
        tenant_id,
        id_,
        idempotency_key,
        occurred_at,
        ingested_at,
        engine_id,
        run_id,
        query_text,
        citation_refs,
        raw_object_ref,
    ) = values
    return ObservationRow(
        tenant_id=tenant_id,
        id=id_,
        idempotency_key=idempotency_key,
        occurred_at=_coerce_utc(occurred_at),
        engine_id=engine_id,
        run_id=run_id,
        query_text=query_text,
        citation_refs=tuple(citation_refs),
        raw_object_ref=raw_object_ref,
        ingested_at=_coerce_utc(ingested_at),
    )


def _citation_from_values(values: tuple[object, ...]) -> CitationRow:
    (
        tenant_id,
        id_,
        idempotency_key,
        occurred_at,
        ingested_at,
        run_id,
        observation_id,
        citation_ref,
        source_domain,
        contribution_score,
    ) = values
    return CitationRow(
        tenant_id=tenant_id,
        id=id_,
        idempotency_key=idempotency_key,
        occurred_at=_coerce_utc(occurred_at),
        run_id=run_id,
        observation_id=observation_id,
        citation_ref=citation_ref,
        source_domain=source_domain,
        contribution_score=contribution_score,
        ingested_at=_coerce_utc(ingested_at),
    )


def _experiment_registration_from_values(values: tuple[object, ...]) -> ExperimentRegistrationRow:
    (
        tenant_id,
        id_,
        idempotency_key,
        occurred_at,
        ingested_at,
        engine_id,
        locale,
        observation_cell,
        registration_hash,
        status,
    ) = values
    return ExperimentRegistrationRow(
        tenant_id=tenant_id,
        id=id_,
        idempotency_key=idempotency_key,
        occurred_at=_coerce_utc(occurred_at),
        engine_id=engine_id,
        locale=locale,
        observation_cell=observation_cell,
        registration_hash=registration_hash,
        status=status,
        ingested_at=_coerce_utc(ingested_at),
    )


class ClickHouseAnalyticsStore:
    """Adapter over an injected `ClickHouseExecutor` — this package's public
    surface (`__init__.py` re-exports this class)."""

    def __init__(self, executor: ClickHouseExecutor) -> None:
        self._executor = executor

    # --- append (idempotent by (tenant_id, idempotency_key)) --------------------

    def append_observation(self, row: ObservationRow) -> bool:
        """Insert `row` into `observations` unless `(tenant_id,
        idempotency_key)` is already present. Returns `True` if a new row
        was inserted, `False` on an idempotent-replay no-op."""
        return self._append("observations", row, _observation_fields(row))

    def append_citation(self, row: CitationRow) -> bool:
        return self._append("citations", row, _citation_fields(row))

    def append_experiment_registration(self, row: ExperimentRegistrationRow) -> bool:
        return self._append("experiment_registrations", row, _experiment_registration_fields(row))

    def _append(
        self,
        table: str,
        row: ObservationRow | CitationRow | ExperimentRegistrationRow,
        fields_map: dict[str, object],
    ) -> bool:
        validate_tenant_id(row.tenant_id)
        if self._exists_idempotency_key(table, row.tenant_id, row.idempotency_key):
            return False
        columns, values = build_insert_columns(table, fields_map)
        self._executor.insert_rows(table, columns, [values])
        return True

    def _exists_idempotency_key(self, table: str, tenant_id: str, idempotency_key: str) -> bool:
        query = AnalyticsQuery.for_tenant(table, tenant_id).filter_eq(
            "idempotency_key", idempotency_key
        )
        sql, params = query.to_select_sql(columns=("id",))
        return len(self._executor.query(sql, params)) > 0

    # --- query (every method REQUIRES tenant_id as the first argument) ----------

    def get_observations(
        self,
        tenant_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[ObservationRow, ...]:
        """Return every `observations` row for `tenant_id` (optionally
        bounded by `[start, end)`/`limit`) — a query for ANY other tenant's
        rows is not expressible through this method signature at all."""
        query = AnalyticsQuery.for_tenant("observations", tenant_id).with_time_range(
            start=start, end=end
        )
        if limit is not None:
            query = query.with_limit(limit)
        sql, params = query.to_select_sql(columns=_OBSERVATIONS_SELECT_COLUMNS)
        return tuple(
            _observation_from_values(tuple(row)) for row in self._executor.query(sql, params)
        )

    def get_citations(
        self,
        tenant_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[CitationRow, ...]:
        query = AnalyticsQuery.for_tenant("citations", tenant_id).with_time_range(
            start=start, end=end
        )
        if limit is not None:
            query = query.with_limit(limit)
        sql, params = query.to_select_sql(columns=_CITATIONS_SELECT_COLUMNS)
        return tuple(_citation_from_values(tuple(row)) for row in self._executor.query(sql, params))

    def get_experiment_registrations(
        self,
        tenant_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[ExperimentRegistrationRow, ...]:
        query = AnalyticsQuery.for_tenant("experiment_registrations", tenant_id).with_time_range(
            start=start, end=end
        )
        if limit is not None:
            query = query.with_limit(limit)
        sql, params = query.to_select_sql(columns=_EXPERIMENT_REGISTRATIONS_SELECT_COLUMNS)
        return tuple(
            _experiment_registration_from_values(tuple(row))
            for row in self._executor.query(sql, params)
        )


__all__ = ["ClickHouseAnalyticsStore"]

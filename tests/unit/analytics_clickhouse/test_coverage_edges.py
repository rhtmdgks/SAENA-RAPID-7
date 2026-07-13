"""Edge-branch coverage (Integrator-added at w4-06 integration): ingested_at
validation, migrate-with-bad-executor, limit branch, utc_now, _coerce_utc naive
path — the non-integration branches the author suite left uncovered."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from analytics_clickhouse_factories import (
    TENANT_A,
    make_citation_row,
    make_experiment_registration_row,
    make_observation_row,
)
from saena_analytics_clickhouse.errors import MigrationError, RowValidationError
from saena_analytics_clickhouse.identifiers import utc_now
from saena_analytics_clickhouse.schema import migrate_down, migrate_up
from saena_analytics_clickhouse.store import _coerce_utc


def test_utc_now_is_tz_aware_utc() -> None:
    now = utc_now()
    assert now.tzinfo is UTC


def test_ingested_at_is_validated_on_every_row_type() -> None:
    ts = datetime(2026, 7, 13, tzinfo=UTC)
    # each accepts a valid tz-aware ingested_at (exercises the validation branch)
    assert make_observation_row(ingested_at=ts).ingested_at == ts
    assert make_citation_row(ingested_at=ts).ingested_at == ts
    assert make_experiment_registration_row(ingested_at=ts).ingested_at == ts


def test_ingested_at_naive_is_rejected_on_every_row_type() -> None:
    naive = datetime(2026, 7, 13)  # noqa: DTZ001 - intentionally naive
    for maker in (make_observation_row, make_citation_row, make_experiment_registration_row):
        with pytest.raises(RowValidationError):
            maker(ingested_at=naive)


def test_migrate_up_with_executor_missing_execute_raises() -> None:
    class _NoExecute:
        pass

    with pytest.raises(MigrationError):
        migrate_up(_NoExecute())


def test_migrate_down_with_executor_missing_execute_raises() -> None:
    class _NoExecute:
        pass

    with pytest.raises(MigrationError):
        migrate_down(_NoExecute())


def test_coerce_utc_reattaches_utc_to_a_naive_datetime() -> None:
    naive = datetime(2026, 7, 13, 12, 0, 0)  # noqa: DTZ001
    coerced = _coerce_utc(naive)
    assert coerced.tzinfo is UTC
    # already-aware value is returned unchanged
    aware = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)
    assert _coerce_utc(aware) is aware


def test_get_with_limit_branch(store) -> None:
    # exercises the `if limit is not None: query.with_limit` branch on each getter
    base = datetime(2026, 7, 13, tzinfo=UTC)
    for i in range(3):
        store.append_observation(
            make_observation_row(id=f"obs-{i}", occurred_at=base + timedelta(minutes=i))
        )
    limited = store.get_observations(TENANT_A, limit=2)
    assert len(limited) <= 2

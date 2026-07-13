"""Unit tests for `saena_analytics_clickhouse.query` — structural tenant
injection (w4-06 mission deliverable 2: "every query method REQUIRES
tenant_id and injects it into WHERE — structurally impossible to omit")."""

from __future__ import annotations

import datetime as dt
import inspect

import pytest
from analytics_clickhouse_factories import TENANT_A
from saena_analytics_clickhouse.errors import (
    RowValidationError,
    TenantIsolationError,
    UnknownTableError,
)
from saena_analytics_clickhouse.query import AnalyticsQuery, build_insert_columns


def test_for_tenant_requires_tenant_id_as_non_defaulted_positional_argument() -> None:
    """Structural proof: `tenant_id` has no default value in the signature —
    a caller cannot omit it and fall back to an unscoped query."""
    sig = inspect.signature(AnalyticsQuery.for_tenant)
    tenant_param = sig.parameters["tenant_id"]
    assert tenant_param.default is inspect.Parameter.empty


def test_for_tenant_rejects_unknown_table() -> None:
    with pytest.raises(UnknownTableError):
        AnalyticsQuery.for_tenant("not_a_real_table", TENANT_A)


def test_for_tenant_rejects_invalid_tenant_id() -> None:
    with pytest.raises(RowValidationError):
        AnalyticsQuery.for_tenant("observations", "")


def test_to_select_sql_always_includes_tenant_predicate() -> None:
    query = AnalyticsQuery.for_tenant("observations", TENANT_A)
    sql, params = query.to_select_sql()
    assert "tenant_id = %(tenant_id)s" in sql
    assert params["tenant_id"] == TENANT_A


def test_filter_eq_appends_without_removing_tenant_predicate() -> None:
    query = AnalyticsQuery.for_tenant("observations", TENANT_A).filter_eq(
        "idempotency_key", "idem-1"
    )
    sql, params = query.to_select_sql()
    assert "tenant_id = %(tenant_id)s" in sql
    assert "idempotency_key = %(" in sql
    assert params["tenant_id"] == TENANT_A
    assert "idem-1" in params.values()


def test_with_time_range_appends_bounds() -> None:
    start = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    end = dt.datetime(2026, 2, 1, tzinfo=dt.UTC)
    query = AnalyticsQuery.for_tenant("observations", TENANT_A).with_time_range(
        start=start, end=end
    )
    sql, params = query.to_select_sql()
    assert "occurred_at >= %(range_start)s" in sql
    assert "occurred_at < %(range_end)s" in sql
    assert params["range_start"] == start
    assert params["range_end"] == end


def test_with_limit_appends_limit_clause() -> None:
    query = AnalyticsQuery.for_tenant("observations", TENANT_A).with_limit(5)
    sql, _ = query.to_select_sql()
    assert "LIMIT 5" in sql


def test_with_limit_rejects_non_positive() -> None:
    query = AnalyticsQuery.for_tenant("observations", TENANT_A)
    with pytest.raises(ValueError, match="limit must be >= 1"):
        query.with_limit(0)


def test_query_is_frozen_and_immutable() -> None:
    query = AnalyticsQuery.for_tenant("observations", TENANT_A)
    with pytest.raises(AttributeError):
        query.tenant_id = "other-co"  # type: ignore[misc]


def test_filter_eq_returns_new_instance_original_unchanged() -> None:
    base = AnalyticsQuery.for_tenant("observations", TENANT_A)
    derived = base.filter_eq("idempotency_key", "idem-1")
    assert derived is not base
    assert base.where_sql == ("tenant_id = %(tenant_id)s",)
    assert len(derived.where_sql) == 2


def test_build_insert_columns_requires_tenant_id() -> None:
    with pytest.raises(TenantIsolationError):
        build_insert_columns("observations", {"id": "obs-1"})


def test_build_insert_columns_rejects_empty_tenant_id() -> None:
    with pytest.raises(TenantIsolationError):
        build_insert_columns("observations", {"tenant_id": "", "id": "obs-1"})


def test_build_insert_columns_rejects_unknown_table() -> None:
    with pytest.raises(UnknownTableError):
        build_insert_columns("not_a_real_table", {"tenant_id": TENANT_A})


def test_build_insert_columns_returns_columns_and_values_in_order() -> None:
    columns, values = build_insert_columns("observations", {"tenant_id": TENANT_A, "id": "obs-1"})
    assert columns == ("tenant_id", "id")
    assert values == (TENANT_A, "obs-1")

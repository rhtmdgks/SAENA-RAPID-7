"""Unit tests: SQL generation for `measurement_outcome` reads (w5-11) —
tenant injection, dedup SQL shape, raw-vs-adjusted view SQL."""

from __future__ import annotations

from saena_analytics_clickhouse.query import AnalyticsQuery


class TestTenantInjection:
    def test_for_tenant_bakes_tenant_predicate_into_where_sql(self) -> None:
        query = AnalyticsQuery.for_tenant("measurement_outcome", "acme-co")
        assert query.where_sql == ("tenant_id = %(tenant_id)s",)
        assert query.params == {"tenant_id": "acme-co"}

    def test_select_sql_always_contains_tenant_predicate(self) -> None:
        query = AnalyticsQuery.for_tenant("measurement_outcome", "acme-co")
        sql, params = query.to_select_sql(columns=("id",))
        assert "tenant_id = %(tenant_id)s" in sql
        assert params == {"tenant_id": "acme-co"}


class TestDeduplicatedSelectSql:
    def test_dedup_sql_uses_limit_1_by_tenant_and_idempotency_key(self) -> None:
        query = AnalyticsQuery.for_tenant("measurement_outcome", "acme-co")
        sql, _params = query.to_deduplicated_select_sql(columns=("id", "b_verdict"))
        assert "LIMIT 1 BY tenant_id, idempotency_key" in sql
        assert "ORDER BY id ASC" in sql

    def test_dedup_sql_applies_outer_pagination_after_dedup(self) -> None:
        query = AnalyticsQuery.for_tenant("measurement_outcome", "acme-co").with_limit(5)
        sql, _params = query.to_deduplicated_select_sql(columns=("id",))
        assert sql.rstrip().endswith("LIMIT 5")
        # the LIMIT must be OUTSIDE the inner LIMIT 1 BY subselect.
        outer_part = sql.split(")", 1)[1]
        assert "LIMIT 5" in outer_part

    def test_dedup_sql_applies_time_range_inside_inner_query(self) -> None:
        import datetime as dt

        query = AnalyticsQuery.for_tenant("measurement_outcome", "acme-co").with_time_range(
            start=dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
        )
        sql, params = query.to_deduplicated_select_sql(columns=("id",))
        # SQL shape: "SELECT ... FROM (<inner>) ORDER BY ..." — the inner
        # subselect is everything between the FIRST "(" and the matching
        # "LIMIT 1 BY ..." close, which is where the WHERE clause lives.
        inner_part = sql.split("(", 1)[1].split("LIMIT 1 BY", 1)[0]
        assert "occurred_at >= %(range_start)s" in inner_part
        assert params["range_start"] == dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
        assert params["range_start"] == dt.datetime(2026, 7, 1, tzinfo=dt.UTC)


class TestRawVsAdjustedSelectSql:
    def test_projects_both_lift_columns(self) -> None:
        query = AnalyticsQuery.for_tenant("measurement_outcome", "acme-co")
        sql, _params = query.to_raw_vs_adjusted_select_sql()
        assert "raw_lift" in sql
        assert "net_of_control_lift" in sql

    def test_projects_the_fixed_column_set_in_order(self) -> None:
        query = AnalyticsQuery.for_tenant("measurement_outcome", "acme-co")
        sql, _params = query.to_raw_vs_adjusted_select_sql()
        # inner SELECT column list should be the fixed projection, in order.
        inner_select = sql.split("FROM", 1)[0]
        assert inner_select.index("tenant_id") < inner_select.index("experiment_id")
        assert inner_select.index("raw_lift") < inner_select.index("net_of_control_lift")

    def test_is_still_tenant_scoped(self) -> None:
        query = AnalyticsQuery.for_tenant("measurement_outcome", "acme-co")
        sql, params = query.to_raw_vs_adjusted_select_sql()
        assert "tenant_id = %(tenant_id)s" in sql
        assert params["tenant_id"] == "acme-co"

    def test_reuses_the_unconditional_logical_dedup_mechanism(self) -> None:
        """The raw-vs-adjusted view must not invent a second, non-deduplicated
        query shape — it reuses `to_deduplicated_select_sql`'s exact
        `LIMIT 1 BY` mechanism (r4-02 unconditional dedup)."""
        query = AnalyticsQuery.for_tenant("measurement_outcome", "acme-co")
        sql, _params = query.to_raw_vs_adjusted_select_sql()
        assert "LIMIT 1 BY tenant_id, idempotency_key" in sql

    def test_can_narrow_to_one_experiment_via_filter_eq(self) -> None:
        query = AnalyticsQuery.for_tenant("measurement_outcome", "acme-co").filter_eq(
            "experiment_id", "exp-1"
        )
        sql, params = query.to_raw_vs_adjusted_select_sql()
        assert "experiment_id = %(eq_experiment_id_1)s" in sql
        assert params["eq_experiment_id_1"] == "exp-1"

"""Unit tests for `measurement_outcome`'s DDL shape (w5-11) —
PARTITION/ORDER-BY conventions + migration wiring."""

from __future__ import annotations

from saena_analytics_clickhouse.schema import MIGRATIONS, TABLE_NAMES


def test_measurement_outcome_is_a_registered_table() -> None:
    assert "measurement_outcome" in TABLE_NAMES


def _measurement_outcome_ddl() -> str:
    for migration in MIGRATIONS:
        for statement in migration.up_sql:
            if "CREATE TABLE IF NOT EXISTS measurement_outcome" in statement:
                return statement
    raise AssertionError("no CREATE TABLE found for measurement_outcome")


class TestPartitionAndOrderBy:
    def test_is_time_partitioned(self) -> None:
        ddl = _measurement_outcome_ddl()
        assert "PARTITION BY toYYYYMM(occurred_at)" in ddl

    def test_is_tenant_prefixed_order_by(self) -> None:
        ddl = _measurement_outcome_ddl()
        assert "ORDER BY (tenant_id, occurred_at, id)" in ddl

    def test_partition_expression_never_references_tenant_id(self) -> None:
        """ADR-0007 rev.2 §5: per-tenant partitioning is FORBIDDEN."""
        ddl = _measurement_outcome_ddl()
        partition_line = next(line for line in ddl.splitlines() if "PARTITION BY" in line)
        assert "tenant_id" not in partition_line

    def test_no_ttl_clause(self) -> None:
        """Retention is OPEN — same policy as every sibling table."""
        ddl = _measurement_outcome_ddl()
        assert "TTL" not in ddl.upper()

    def test_is_a_plain_mergetree_with_dedup_window_setting(self) -> None:
        ddl = _measurement_outcome_ddl()
        assert "ENGINE = MergeTree" in ddl
        assert "non_replicated_deduplication_window" in ddl


class TestColumnShape:
    def test_declares_b_verdict_as_low_cardinality(self) -> None:
        ddl = _measurement_outcome_ddl()
        assert "b_verdict LowCardinality(String)" in ddl

    def test_declares_outcome_layer_as_low_cardinality(self) -> None:
        ddl = _measurement_outcome_ddl()
        assert "outcome_layer LowCardinality(String)" in ddl

    def test_declares_reason_codes_as_array(self) -> None:
        ddl = _measurement_outcome_ddl()
        assert "reason_codes Array(LowCardinality(String))" in ddl

    def test_declares_both_lift_columns_as_nullable_float(self) -> None:
        ddl = _measurement_outcome_ddl()
        assert "net_of_control_lift Nullable(Float64)" in ddl
        assert "raw_lift Nullable(Float64)" in ddl

    def test_never_declares_a_raw_content_column(self) -> None:
        """Metadata-safe-only requirement: no raw response/screenshot/query
        column may ever appear on this table."""
        ddl = _measurement_outcome_ddl()
        for forbidden in ("raw_response", "raw_html", "screenshot", "query_text", "response_body"):
            assert forbidden not in ddl

    def test_declares_hash_only_evidence_and_policy_cross_references(self) -> None:
        ddl = _measurement_outcome_ddl()
        assert "registration_canonical_hash String" in ddl
        assert "evidence_bundle_manifest_hash String" in ddl
        assert "grs_policy_hash String" in ddl
        assert "evidence_basis_id Nullable(String)" in ddl


def test_measurement_outcome_migration_is_additive_not_a_0001_edit() -> None:
    """w5-11 registers `measurement_outcome` as a NEW migration entry, never
    a same-commit edit of `MIGRATIONS[0]` (the w4-06 tables) — this is the
    same EXPAND-only discipline `schema.py`'s own "Expand/contract policy"
    docstring requires."""
    assert not any("measurement_outcome" in statement for statement in MIGRATIONS[0].up_sql)
    assert any(
        "measurement_outcome" in statement
        for migration in MIGRATIONS[1:]
        for statement in migration.up_sql
    )


def test_measurement_outcome_migration_has_a_reversing_down_sql() -> None:
    owning_migration = next(
        m for m in MIGRATIONS if any("measurement_outcome" in s for s in m.up_sql)
    )
    assert any("DROP TABLE IF EXISTS measurement_outcome" in s for s in owning_migration.down_sql)

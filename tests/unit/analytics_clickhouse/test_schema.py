"""Unit tests for `saena_analytics_clickhouse.schema` — DDL shape + reversible
migrations (w4-06 mission deliverable 1)."""

from __future__ import annotations

import pytest
from analytics_clickhouse_factories import FakeClickHouseExecutor
from saena_analytics_clickhouse.errors import UnknownTableError
from saena_analytics_clickhouse.schema import (
    MIGRATIONS,
    TABLE_NAMES,
    migrate_down,
    migrate_up,
    require_known_table,
)


def test_table_names_match_mission_scope() -> None:
    # w5-11 (Wave 5) additively registers `measurement_outcome` alongside the
    # three w4-06 tables — same EXPAND-only convention `schema.py`'s own
    # "Expand/contract policy" docstring already documents (a new table is a
    # new, separate `CREATE TABLE IF NOT EXISTS`, never a same-commit edit of
    # an existing one). This assertion is updated here (not in w5-11's own
    # exclusive test path) only because it hard-codes the exact tuple and
    # would otherwise spuriously fail — no other line in this file changes.
    assert TABLE_NAMES == (
        "observations",
        "citations",
        "experiment_registrations",
        "measurement_outcome",
    )


@pytest.mark.parametrize("table", TABLE_NAMES)
def test_require_known_table_accepts_owned_tables(table: str) -> None:
    require_known_table(table)  # does not raise


def test_require_known_table_rejects_unknown_table() -> None:
    with pytest.raises(UnknownTableError):
        require_known_table("not_a_real_table")


@pytest.mark.parametrize("table", TABLE_NAMES)
def test_every_table_ddl_is_time_partitioned_and_tenant_prefixed(table: str) -> None:
    """ADR-0007 rev.2 §5: time partition + `ORDER BY (tenant_id, ...)`
    prefix — no per-tenant partition.

    Searches every migration's `up_sql` (not just `MIGRATIONS[0]`) — w5-11
    (Wave 5) additively registers `measurement_outcome` in `MIGRATIONS[1]`
    (a NEW migration entry, never a same-commit edit of `MIGRATIONS[0]`, per
    `schema.py`'s own "Expand/contract policy"), so a table-name-agnostic
    lookup across all migrations is what "every table this package owns" now
    actually requires."""
    up_statements = [s for migration in MIGRATIONS for s in migration.up_sql]
    matching = [s for s in up_statements if f"CREATE TABLE IF NOT EXISTS {table}" in s]
    assert len(matching) == 1
    ddl = matching[0]
    assert "PARTITION BY toYYYYMM(occurred_at)" in ddl
    assert "ORDER BY (tenant_id, occurred_at, id)" in ddl
    assert "tenant_id String" in ddl
    # Per-tenant partitioning is FORBIDDEN — the partition expression must
    # never reference tenant_id.
    partition_line = next(line for line in ddl.splitlines() if "PARTITION BY" in line)
    assert "tenant_id" not in partition_line


def test_no_table_emits_a_ttl_clause() -> None:
    """TTL/retention is OPEN (README.md) — no CREATE TABLE may emit TTL.

    Checks every migration's `up_sql` (see the DDL-shape test above for why)."""
    for migration in MIGRATIONS:
        for statement in migration.up_sql:
            assert "TTL" not in statement.upper() or "TTL" not in statement


def test_observations_ddl_has_no_query_text_column() -> None:
    """r4-04 leak-closure proof at the DDL level: the `observations`
    CREATE TABLE statement must never define a `query_text` column again —
    the pre-fix column that stored the raw customer query verbatim."""
    (ddl,) = [s for s in MIGRATIONS[0].up_sql if "CREATE TABLE IF NOT EXISTS observations" in s]
    assert "query_text" not in ddl


def test_observations_ddl_has_query_ref_and_query_digest_columns() -> None:
    (ddl,) = [s for s in MIGRATIONS[0].up_sql if "CREATE TABLE IF NOT EXISTS observations" in s]
    assert "query_ref String" in ddl
    assert "query_digest Nullable(String)" in ddl


def test_migrate_up_creates_every_table() -> None:
    executor = FakeClickHouseExecutor()
    migrate_up(executor)
    assert set(executor.tables.keys()) == set(TABLE_NAMES)


def test_migrate_down_drops_every_table() -> None:
    executor = FakeClickHouseExecutor()
    migrate_up(executor)
    migrate_down(executor)
    assert executor.tables == {}


def test_migrate_down_reverses_migrate_up_ddl_order() -> None:
    executor = FakeClickHouseExecutor()
    migrate_up(executor)
    up_log = list(executor.ddl_log)
    executor.ddl_log.clear()
    migrate_down(executor)
    down_log = executor.ddl_log
    up_tables = [s.split()[5] for s in up_log]  # CREATE TABLE IF NOT EXISTS <name>
    down_tables = [s.split()[-1] if "DROP" in s else s for s in down_log]
    assert down_tables == list(reversed(up_tables))

"""Unit tests for the pure SQL builders + migration loading (w5-10) — no DB.

These assert the STRUCTURAL properties the adapter/integration lane relies on
(schema-qualified identifiers, ON CONFLICT arbiters, no interpolated
caller-values, additive-only migration shape) without ever touching a database.
"""

from __future__ import annotations

from saena_experiment_attribution.persistence import tables


def test_schema_is_own_dedicated_schema() -> None:
    # Own-schema-per-service (ADR-0007): distinct from every other unit's schema.
    assert tables.SCHEMA_NAME == "saena_experiment_attribution"
    assert tables.SCHEMA_NAME not in {"saena_persistence", "saena_vector"}


def test_qualified_table_is_schema_scoped_and_quoted() -> None:
    assert (
        tables.qualified_table("confirmations") == '"saena_experiment_attribution"."confirmations"'
    )


def test_every_insert_uses_on_conflict_do_nothing() -> None:
    # ON CONFLICT DO NOTHING (never DO UPDATE) is what makes the first writer
    # win and the read-back-compare decide duplicate-vs-conflict.
    for builder in (
        tables.insert_confirmation_sql,
        tables.insert_window_sql,
        tables.insert_decision_sql,
        tables.insert_evidence_sql,
    ):
        sql = builder()
        assert "ON CONFLICT" in sql
        assert "DO NOTHING" in sql
        assert "DO UPDATE" not in sql
        assert "RETURNING" in sql


def test_inserts_carry_content_fingerprint_column() -> None:
    for builder in (
        tables.insert_confirmation_sql,
        tables.insert_window_sql,
        tables.insert_decision_sql,
        tables.insert_evidence_sql,
    ):
        assert "content_fingerprint" in builder()


def test_window_conflict_arbiter_is_the_partial_active_index() -> None:
    # At-most-one-active is enforced against the partial unique index, so the
    # ON CONFLICT target must be the `WHERE active` predicate index.
    sql = tables.insert_window_sql()
    assert "ON CONFLICT (tenant_id, experiment_id) WHERE active" in sql


def test_keys_are_tenant_first() -> None:
    # tenant_id-first composite keys (ADR-0014): every ON CONFLICT / WHERE key
    # leads with tenant_id.
    assert "ON CONFLICT (tenant_id, confirmation_key)" in tables.insert_confirmation_sql()
    assert "ON CONFLICT (tenant_id, experiment_id, decision_slot)" in tables.insert_decision_sql()
    assert "ON CONFLICT (tenant_id, manifest_hash)" in tables.insert_evidence_sql()


def test_selects_filter_by_tenant_first() -> None:
    for builder in (
        tables.select_confirmation_sql,
        tables.select_window_sql,
        tables.select_decision_sql,
        tables.select_evidence_sql,
        tables.list_decisions_sql,
    ):
        assert "WHERE tenant_id = :tenant_id" in builder()


def test_list_decisions_is_append_ordered() -> None:
    assert "ORDER BY seq ASC" in tables.list_decisions_sql()


def test_no_caller_value_is_string_interpolated() -> None:
    # Every caller/tenant value is a bind parameter (`:name`), never an f-string
    # hole — no SQL-injection surface. Only fixed schema/column identifiers are
    # interpolated, and those contain no `{`/`}` after building.
    for builder in (
        tables.insert_confirmation_sql,
        tables.insert_window_sql,
        tables.insert_decision_sql,
        tables.insert_evidence_sql,
        tables.select_confirmation_sql,
        tables.select_window_sql,
        tables.select_decision_sql,
        tables.select_evidence_sql,
        tables.list_decisions_sql,
    ):
        sql = builder()
        assert "{" not in sql and "}" not in sql
        assert ":tenant_id" in sql


def test_truncate_covers_all_four_tables_with_cascade() -> None:
    sql = tables.truncate_all_sql()
    for table in ("confirmations", "measurement_windows", "outcome_decisions", "evidence_bundles"):
        assert table in sql
    assert sql.endswith("CASCADE")


def test_migration_sql_loads_additive_schema() -> None:
    (migration,) = tables.migration_sql()
    # Additive-only shape: every DDL is IF-NOT-EXISTS / CREATE-OR-REPLACE, and
    # the append-only trigger + partial unique index are present.
    assert "CREATE SCHEMA IF NOT EXISTS" in migration
    assert migration.count("CREATE TABLE IF NOT EXISTS") == 4
    assert "ux_measurement_windows_active_key" in migration
    assert "WHERE active" in migration
    assert "deny_decision_mutation" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    # No destructive DDL (DROP TABLE / DROP SCHEMA / ALTER ... DROP).
    assert "DROP TABLE" not in migration
    assert "DROP SCHEMA" not in migration


def test_migration_filenames_are_ordered_and_numbered() -> None:
    assert tables.MIGRATION_FILENAMES == ("0001_measurement_schema.sql",)

"""Integration tests — real ClickHouse container schema creation +
migration reversibility (w4-06 mission deliverable 5: "schema, ...,
migration up/down").

Docker unavailable / `clickhouse-connect` not installed -> every test in
this module is skipped with an honest, distinct reason
(`conftest.py::pytest_collection_modifyitems`), never silently passed.
"""

from __future__ import annotations

import pytest
from saena_analytics_clickhouse.executor import ClickHouseConnectExecutor
from saena_analytics_clickhouse.schema import TABLE_NAMES, migrate_down, migrate_up

pytestmark = pytest.mark.integration


class TestSchemaCreation:
    def test_every_owned_table_exists_and_is_empty_after_session_migrate_up(
        self, executor: ClickHouseConnectExecutor
    ) -> None:
        for table in TABLE_NAMES:
            rows = executor.query(f"SELECT count() FROM {table}")
            assert rows[0][0] == 0

    def test_tables_are_ordered_by_tenant_id_first(
        self, executor: ClickHouseConnectExecutor
    ) -> None:
        for table in TABLE_NAMES:
            rows = executor.query(
                "SELECT sorting_key FROM system.tables WHERE name = %(table)s AND "
                "database = currentDatabase()",
                {"table": table},
            )
            (sorting_key,) = rows[0]
            assert sorting_key.startswith("tenant_id")


class TestMigrationReversibility:
    def test_migrate_down_then_migrate_up_recreates_every_table(
        self, executor: ClickHouseConnectExecutor
    ) -> None:
        migrate_down(executor)
        for table in TABLE_NAMES:
            with pytest.raises(Exception):  # noqa: B017 - real ClickHouse "unknown table" error
                executor.query(f"SELECT count() FROM {table}")
        # Restore for any other test sharing this session-scoped container.
        migrate_up(executor)
        for table in TABLE_NAMES:
            rows = executor.query(f"SELECT count() FROM {table}")
            assert rows[0][0] == 0

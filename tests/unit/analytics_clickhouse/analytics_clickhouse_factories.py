"""Factory helpers + in-memory `ClickHouseExecutor` fake for
`tests/unit/analytics_clickhouse`.

Deliberately NOT named `conftest.py`'s own module surface — pytest's default
`prepend` import mode collides a SECOND directory's `from conftest import
...` against whichever `conftest` module is already cached under the bare
top-level name `conftest` when the full `tests/unit` suite is collected
together (proven empirically elsewhere in this repo:
`tests/unit/domain_persistence/persistence_factories.py`'s own docstring,
`tests/integration/persistence_postgres/conftest.py`'s own docstring). This
module is imported by its own unique dotted name
(`analytics_clickhouse_factories`, inserted onto `sys.path` by this
directory's `conftest.py`) to avoid that collision entirely — this file is
NEVER itself named `conftest.py`, and no test module here does
`from conftest import ...`.

`FakeClickHouseExecutor` implements `saena_analytics_clickhouse.executor.
ClickHouseExecutor` structurally (duck-typed, `runtime_checkable` Protocol)
with ZERO I/O — an in-memory `dict[table_name, list[dict[column, value]]]`.
It does not parse arbitrary SQL; it understands exactly the fixed,
predictable shapes `query.py`'s `TenantScopedQuery.to_select_sql` /
`schema.py`'s DDL strings emit (see this module's own docstrings on each
helper) — a deliberately narrow, controlled test double, not a general SQL
engine, matching this package's own "pure adapter over a fixed builder
DSL" design.
"""

from __future__ import annotations

import re
from typing import Any

from saena_analytics_clickhouse.rows import CitationRow, ExperimentRegistrationRow, ObservationRow
from saena_analytics_clickhouse.schema import TABLE_NAMES

TENANT_A = "acme-co"
TENANT_B = "globex-co"

_EQ_PARAM_RE = re.compile(r"^eq_(.+)_(\d+)$")
_FROM_RE = re.compile(r"FROM\s+(\w+)", re.IGNORECASE)
_SELECT_RE = re.compile(r"SELECT\s+(.+?)\s+FROM", re.IGNORECASE)
_LIMIT_RE = re.compile(r"LIMIT\s+(\d+)", re.IGNORECASE)
_DDL_TABLE_RE = re.compile(
    r"(?:CREATE|DROP)\s+TABLE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(\w+)", re.IGNORECASE
)


class FakeClickHouseExecutor:
    """In-memory `ClickHouseExecutor` — see module docstring."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.ddl_log: list[str] = []

    # --- ClickHouseExecutor Protocol methods --------------------------------

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.ddl_log.append(sql)
        stripped = sql.strip()
        match = _DDL_TABLE_RE.search(stripped)
        if match is None:
            return
        table = match.group(1)
        if stripped.upper().startswith("DROP"):
            self.tables.pop(table, None)
        elif stripped.upper().startswith("CREATE"):
            self.tables.setdefault(table, [])

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple[Any, ...]]:
        params = params or {}
        table = _extract_table(sql)
        rows = self.tables.get(table, [])
        filtered = [row for row in rows if _matches(row, params)]
        limit_match = _LIMIT_RE.search(sql)
        if limit_match is not None:
            filtered = filtered[: int(limit_match.group(1))]
        columns = _select_columns(sql)
        return [tuple(row.get(column) for column in columns) for row in filtered]

    def insert_rows(
        self, table: str, columns: tuple[str, ...] | list[str], rows: list[tuple[Any, ...]]
    ) -> None:
        stored = self.tables.setdefault(table, [])
        for values in rows:
            stored.append(dict(zip(columns, values, strict=True)))


def _extract_table(sql: str) -> str:
    match = _FROM_RE.search(sql)
    assert match is not None, "query SQL must contain a FROM clause"
    return match.group(1)


def _matches(row: dict[str, Any], params: dict[str, Any]) -> bool:
    for key, value in params.items():
        if key == "tenant_id":
            if row.get("tenant_id") != value:
                return False
        elif key == "range_start":
            if row.get("occurred_at") < value:
                return False
        elif key == "range_end":
            if not (row.get("occurred_at") < value):
                return False
        else:
            eq_match = _EQ_PARAM_RE.match(key)
            if eq_match is not None:
                column = eq_match.group(1)
                if row.get(column) != value:
                    return False
    return True


def _select_columns(sql: str) -> list[str]:
    match = _SELECT_RE.search(sql)
    assert match is not None, "query SQL must contain a SELECT clause"
    return [c.strip() for c in match.group(1).split(",")]


def new_fake_executor_with_tables() -> FakeClickHouseExecutor:
    """A `FakeClickHouseExecutor` pre-seeded with every table this package
    owns (mirrors `migrate_up` having already run)."""
    executor = FakeClickHouseExecutor()
    for table in TABLE_NAMES:
        executor.tables[table] = []
    return executor


def make_observation_row(**overrides: Any) -> ObservationRow:
    import datetime as _dt

    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "id": "obs-1",
        "idempotency_key": "idem-obs-1",
        "occurred_at": _dt.datetime(2026, 7, 1, tzinfo=_dt.UTC),
        "engine_id": "chatgpt-search",
        "run_id": "run-1",
        "query_text": "best crm for startups",
        "citation_refs": ("ref://citation/1",),
        "raw_object_ref": "ref://object/1",
    }
    fields.update(overrides)
    return ObservationRow(**fields)


def make_citation_row(**overrides: Any) -> CitationRow:
    import datetime as _dt

    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "id": "cit-1",
        "idempotency_key": "idem-cit-1",
        "occurred_at": _dt.datetime(2026, 7, 1, tzinfo=_dt.UTC),
        "run_id": "run-1",
        "observation_id": "obs-1",
        "citation_ref": "ref://citation/1",
        "source_domain": "example.com",
        "contribution_score": 0.5,
    }
    fields.update(overrides)
    return CitationRow(**fields)


def make_experiment_registration_row(**overrides: Any) -> ExperimentRegistrationRow:
    import datetime as _dt

    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "id": "exp-1",
        "idempotency_key": "idem-exp-1",
        "occurred_at": _dt.datetime(2026, 7, 1, tzinfo=_dt.UTC),
        "engine_id": "chatgpt-search",
        "locale": "en-US",
        "observation_cell": "cell-1",
        "registration_hash": "sha256:abc123",
        "status": "registered",
    }
    fields.update(overrides)
    return ExperimentRegistrationRow(**fields)


__all__ = [
    "TENANT_A",
    "TENANT_B",
    "FakeClickHouseExecutor",
    "make_citation_row",
    "make_experiment_registration_row",
    "make_observation_row",
    "new_fake_executor_with_tables",
]

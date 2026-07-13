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

import os
import re
import threading
from typing import Any

from saena_analytics_clickhouse.query_privacy import QuerySigningKeyRef, derive_query_ref
from saena_analytics_clickhouse.rows import CitationRow, ExperimentRegistrationRow, ObservationRow
from saena_analytics_clickhouse.schema import TABLE_NAMES

TENANT_A = "acme-co"
TENANT_B = "globex-co"

# `derive_query_ref` (independent-critic MUST-FIX round 2) is now KEYED and
# fail-closed, exactly like `derive_query_digest` always was — this factory
# module needs a deterministic test signing key to keep building
# `ObservationRow` fixtures without every call site threading a real
# `SecretRef` through. A DEDICATED env var name (never
# `QUERY_SIGNING_KEY_ENV_VAR` itself), set once at module-import time to a
# fixed, obviously-synthetic value — never a real secret, never read from
# any production key source. `os.environ.setdefault` (not a plain assign) so
# a real test run that already set this var for its own reason is never
# silently overwritten.
_TEST_QUERY_SIGNING_KEY_ENV_VAR = "SAENA_ANALYTICS_QUERY_SIGNING_KEY__TEST_FIXTURE"
os.environ.setdefault(_TEST_QUERY_SIGNING_KEY_ENV_VAR, "test-fixture-signing-key-not-a-real-secret")
_TEST_SIGNING_KEY_REF = QuerySigningKeyRef(env_var=_TEST_QUERY_SIGNING_KEY_ENV_VAR)

_EQ_PARAM_RE = re.compile(r"^eq_(.+)_(\d+)$")
_FROM_RE = re.compile(r"FROM\s+(\w+)", re.IGNORECASE)
_SELECT_RE = re.compile(r"SELECT\s+(.+?)\s+FROM", re.IGNORECASE)
_LIMIT_RE = re.compile(r"LIMIT\s+(\d+)", re.IGNORECASE)
# r4-02 follow-on: the dedup SELECT nests `... ORDER BY <winner> LIMIT 1 BY
# <dedup cols>` inside an outer `... ORDER BY <display> [LIMIT <pagination>]`.
# This fake must simulate ClickHouse's `LIMIT 1 BY` LOGICAL dedup (one row per
# BY-group, the winner-order-minimal), then apply the OUTER pagination limit —
# matching what the real server does (verified by the live integration suite).
_LIMIT_1_BY_RE = re.compile(r"LIMIT\s+1\s+BY\s+([\w,\s]+?)\s*\)", re.IGNORECASE)
_INNER_WINNER_ORDER_RE = re.compile(r"ORDER BY\s+([\w,\s]+?)\s+LIMIT\s+1\s+BY", re.IGNORECASE)
_OUTER_LIMIT_RE = re.compile(r"LIMIT\s+(\d+)\s*$", re.IGNORECASE)
_DDL_TABLE_RE = re.compile(
    r"(?:CREATE|DROP)\s+TABLE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(\w+)", re.IGNORECASE
)


class FakeClickHouseExecutor:
    """In-memory `ClickHouseExecutor` — see module docstring.

    `dedup_token` support (r4-02): this fake simulates ClickHouse's REAL
    server-side `insert_deduplication_token` behavior (verified against a
    live container as part of the r4-02 fix, see `store.py`'s module
    docstring) closely enough for deterministic unit coverage of
    `ClickHouseAnalyticsStore`'s dedup-driven `_append`/`_won_dedup_race`
    logic: a `(table, dedup_token)` pair that has already been inserted once
    is a NO-OP on every subsequent `insert_rows` call carrying that same
    pair — no second row is appended, mirroring the real server's
    block-level dedup exactly (not merely "the LAST write wins", which would
    misrepresent what a real `dedup_witness` read-back observes: the FIRST
    writer's payload survives, every later duplicate is silently dropped).
    A `threading.Lock` guards the check-and-append pair so this fake itself
    does not reintroduce a check-then-insert race when exercised by a real
    multi-threaded unit test (`test_idempotency_distributed.py`-style
    concurrency assertions against the fake, not just the real container).
    """

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.ddl_log: list[str] = []
        self._seen_dedup_tokens: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

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
        with self._lock:
            rows = list(self.tables.get(table, []))
        filtered = [row for row in rows if _matches(row, params)]
        dedup_match = _LIMIT_1_BY_RE.search(sql)
        if dedup_match is not None:
            # Simulate `ORDER BY <winner> LIMIT 1 BY <cols>`: one row per BY
            # group, the winner-order-minimal (stable, deterministic).
            dedup_cols = [c.strip() for c in dedup_match.group(1).split(",") if c.strip()]
            winner_m = _INNER_WINNER_ORDER_RE.search(sql)
            winner_cols = (
                [c.strip().split()[0] for c in winner_m.group(1).split(",") if c.strip()]
                if winner_m is not None
                else ["id"]
            )
            winners: dict[tuple[Any, ...], tuple[tuple[Any, ...], dict[str, Any]]] = {}
            for row in filtered:
                group_key = tuple(row.get(c) for c in dedup_cols)
                winner_key = tuple(row.get(c) for c in winner_cols)
                current = winners.get(group_key)
                if current is None or winner_key < current[0]:
                    winners[group_key] = (winner_key, row)
            filtered = [row for _, row in winners.values()]
            # Outer display order (deterministic): occurred_at, id.
            filtered.sort(key=lambda r: (r.get("occurred_at"), r.get("id")))
            outer_match = _OUTER_LIMIT_RE.search(sql)
            if outer_match is not None:
                filtered = filtered[: int(outer_match.group(1))]
        else:
            limit_match = _LIMIT_RE.search(sql)
            if limit_match is not None:
                filtered = filtered[: int(limit_match.group(1))]
        columns = _select_columns(sql)
        return [tuple(row.get(column) for column in columns) for row in filtered]

    def insert_rows(
        self,
        table: str,
        columns: tuple[str, ...] | list[str],
        rows: list[tuple[Any, ...]],
        *,
        dedup_token: str | None = None,
    ) -> None:
        with self._lock:
            if dedup_token is not None:
                dedup_key = (table, dedup_token)
                if dedup_key in self._seen_dedup_tokens:
                    # Real ClickHouse block dedup: a repeat of an
                    # already-seen token is a silent no-op — the FIRST
                    # writer's block is what was kept, never overwritten.
                    return
                self._seen_dedup_tokens.add(dedup_key)
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
    """`query_ref` defaults to the `derive_query_ref` (KEYED, r4-04 round 2)
    projection of the SAME synthetic query `make_observation_row` always
    used pre-r4-04 (`"best crm for startups"`) — never a raw `query_text`
    field any more (r4-04: `ObservationRow` has no such field), and never an
    unkeyed hash either (round-2 fix: `derive_query_ref` is fail-closed,
    keyed by `_TEST_SIGNING_KEY_REF` here). A caller that needs to override
    the underlying query should pass `query_ref=derive_query_ref(
    tenant_id=..., raw_query=..., signing_key_ref=_TEST_SIGNING_KEY_REF
    ).query_ref` explicitly, never a raw string."""
    import datetime as _dt

    default_tenant_id = TENANT_A
    fields: dict[str, Any] = {
        "tenant_id": default_tenant_id,
        "id": "obs-1",
        "idempotency_key": "idem-obs-1",
        "occurred_at": _dt.datetime(2026, 7, 1, tzinfo=_dt.UTC),
        "engine_id": "chatgpt-search",
        "run_id": "run-1",
        "query_ref": derive_query_ref(
            tenant_id=overrides.get("tenant_id", default_tenant_id),
            raw_query="best crm for startups",
            signing_key_ref=_TEST_SIGNING_KEY_REF,
        ).query_ref,
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
    "fixture_signing_key_ref",
    "make_citation_row",
    "make_experiment_registration_row",
    "make_observation_row",
    "new_fake_executor_with_tables",
]


def fixture_signing_key_ref() -> QuerySigningKeyRef:
    """The deterministic, obviously-synthetic `QuerySigningKeyRef` this
    module's own factories key `derive_query_ref`/`derive_query_digest`
    calls with — exposed for OTHER test modules in this directory
    (`test_rows.py`, `test_query_privacy.py`) that call `derive_query_ref`
    directly rather than through `make_observation_row`, so every test in
    this package shares the SAME deterministic key rather than each
    reaching for its own ad hoc `monkeypatch.setenv`.

    Deliberately NOT prefixed `test_` — pytest's default `python_functions`
    collection pattern (`test_*`, no custom override in this repo's root
    `pyproject.toml`) would otherwise mistake this for a zero-assertion test
    function and silently "pass" it on every collection.
    """
    return _TEST_SIGNING_KEY_REF

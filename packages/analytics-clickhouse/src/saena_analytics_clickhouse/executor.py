"""Execution seam — a `typing.Protocol` every store/migration call goes
through, plus the ONE real implementation over `clickhouse-connect`.

Why a Protocol seam (mission deliverable 4/5): `store.py`'s
`ClickHouseAnalyticsStore` and `schema.py`'s `migrate_up`/`migrate_down` never
import `clickhouse_connect` themselves — they only call methods on whatever
object implements `ClickHouseExecutor`. This is what makes the unit-test
lane (`tests/unit/analytics_clickhouse/**`) possible WITHOUT a container: an
in-memory fake implementing this exact Protocol (see
`tests/unit/analytics_clickhouse/analytics_clickhouse_factories.py`) stands in
for a real ClickHouse connection with zero I/O. The integration lane
(`tests/integration/clickhouse/**`) instead constructs a real
`ClickHouseConnectExecutor` wrapping `clickhouse_connect.get_client(...)`
against a `testcontainers.clickhouse.ClickHouseContainer`.

`clickhouse-connect` is this package's only third-party runtime dependency
(`pyproject.toml`) and is imported LAZILY inside `ClickHouseConnectExecutor`
methods (not at module import time) so importing
`saena_analytics_clickhouse` — and running the deterministic unit lane, which
never constructs a `ClickHouseConnectExecutor` — never requires
`clickhouse-connect` to be installed at all. This matters concretely for this
patch unit: the Integrator has not yet registered this package as a root
workspace member (see `pyproject.toml`'s Integrator note), so
`clickhouse-connect` is not yet present in the shared `uv.lock`/venv that the
unit lane runs under.

Parameter-binding convention: every `sql` string passed to `execute`/`query`
uses Python `%(name)s`-style placeholders against a `dict` `params` — this is
`clickhouse-connect`'s own client-side binding convention
(`clickhouse_connect.driver.binding.finalize_query`: `query %
{k: format_query_value(v) for k, v in parameters.items()}`), so `query.py`'s
builder output is passed to a real `Client.query`/`.command` completely
unchanged. `params={}`/`None` is a no-op substitution (safe for DDL, which
carries no placeholders).

`insert_rows`'s optional `dedup_token` (r4-02 fix): distributed idempotency
fix, see `store.py` module docstring for the full invariant/mechanism. This
parameter is OPTIONAL, keyword-only, defaulting to `None` — deliberately, so
every PRE-EXISTING `ClickHouseExecutor`-shaped fake in this repo (this
package's own `tests/unit/analytics_clickhouse/analytics_clickhouse_
factories.py::FakeClickHouseExecutor`, and — outside this patch unit's
exclusive write paths — `tests/integration/intelligence_failure/
intelligence_failure_factories.py`'s two executor fakes) keeps working
UNMODIFIED. `store.py._append` introspects each executor's own
`insert_rows` signature once (`_executor_supports_dedup_token`) and only
passes `dedup_token=` to executors that actually declare the parameter — an
executor that predates this fix (3-positional-arg `insert_rows`, no
`dedup_token`) is called exactly the same way it always was, with the SAME
`insert_rows` call count per `append_*` invocation (no second/ledger insert
is ever added — see `store.py` docstring "Why not a second ledger insert").
`ClickHouseConnectExecutor.insert_rows` is the ONE implementation that
actually turns `dedup_token` into a real `clickhouse_connect` `settings={
'insert_deduplication_token': ...}` kwarg on `Client.insert` — the exact,
grounded ClickHouse server setting name/semantics (see `store.py` module
docstring for the live-server verification this patch unit performed).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from saena_analytics_clickhouse.errors import AnalyticsClickHouseError


@runtime_checkable
class ClickHouseExecutor(Protocol):
    """The ONLY interface `schema.py`/`store.py` ever call through.

    Three methods, matching the three shapes of ClickHouse interaction this
    package needs: `execute` (DDL/no-result commands — migrations),
    `query` (SELECT, returns row tuples), `insert_rows` (bulk row insert).
    """

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> None:
        """Run a no-result-set statement (DDL, `DROP TABLE`, etc.)."""
        ...

    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> Sequence[tuple[Any, ...]]:
        """Run a SELECT and return every result row as a plain tuple."""
        ...

    def insert_rows(
        self,
        table: str,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
        *,
        dedup_token: str | None = None,
    ) -> None:
        """Bulk-insert `rows` (each a positional value sequence matching
        `columns`) into `table`.

        `dedup_token` (optional, keyword-only, r4-02): when given, a
        REAL/capable executor (`ClickHouseConnectExecutor`) MUST perform
        this insert as an atomic, server-side deduplicated block insert
        keyed by this exact token string (ClickHouse's native
        `insert_deduplication_token` setting) — never a client-side
        check-then-insert. An executor that does not support this
        parameter at all (a pre-existing fake) is never called with it
        (see module docstring `_executor_supports_dedup_token`)."""
        ...


class ExecutorError(AnalyticsClickHouseError):
    """A `ClickHouseExecutor` implementation failed to perform an operation
    (e.g. the real client raised, or a required third-party dependency is
    not installed)."""

    error_code = "saena.analytics_clickhouse.executor_failed"


class ClickHouseConnectExecutor:
    """Real `ClickHouseExecutor` over `clickhouse_connect.driver.client.Client`.

    Constructed via `create_executor(...)` (below) in every real caller —
    the constructor here accepts an already-built `clickhouse_connect`
    client directly so tests/callers that already hold one (e.g. a
    testcontainers-derived client) can wrap it without going through
    `get_client` twice.
    """

    def __init__(self, client: Any) -> None:  # pragma: no cover - real driver, integration lane
        self._client = client

    def execute(
        self, sql: str, params: Mapping[str, Any] | None = None
    ) -> (
        None
    ):  # pragma: no cover - real clickhouse_connect; covered by tests/integration/clickhouse
        self._client.command(sql, parameters=dict(params) if params else None)

    def query(
        self, sql: str, params: Mapping[str, Any] | None = None
    ) -> Sequence[tuple[Any, ...]]:  # pragma: no cover - real driver, integration lane
        result = self._client.query(sql, parameters=dict(params) if params else None)
        return list(result.result_rows)

    def insert_rows(
        self,
        table: str,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
        *,
        dedup_token: str | None = None,
    ) -> None:  # pragma: no cover - real driver, integration lane
        if not rows:
            return
        settings = {"insert_deduplication_token": dedup_token} if dedup_token is not None else None
        self._client.insert(table, list(rows), column_names=list(columns), settings=settings)


def create_executor(
    *,
    host: str,
    port: int = 8123,
    username: str = "default",
    password: str = "",
    database: str = "default",
    secure: bool = False,
) -> ClickHouseConnectExecutor:
    """Build a `ClickHouseConnectExecutor` from plain connection parameters.

    Raises `ExecutorError` (never a bare `ImportError`) if `clickhouse-connect`
    is not installed — this is the one place in this package that surfaces
    that as a package-native, structured error rather than letting an
    `ImportError` leak straight out of a lazy import.
    """
    try:  # pragma: no cover - real driver import, integration lane
        import clickhouse_connect
    except ImportError as exc:  # pragma: no cover - exercised only when the
        # optional runtime dependency is genuinely absent; see module
        # docstring re: not yet in the shared uv.lock as of this patch unit.
        raise ExecutorError(
            "clickhouse-connect is not installed — cannot build a real "
            "ClickHouseConnectExecutor (see pyproject.toml Integrator note)",
            context={"host": host, "port": port},
        ) from exc
    client = clickhouse_connect.get_client(  # pragma: no cover - real driver, integration lane
        host=host,
        port=port,
        username=username,
        password=password,
        database=database,
        secure=secure,
    )
    return ClickHouseConnectExecutor(client)  # pragma: no cover - real driver, integration lane


__all__ = [
    "ClickHouseConnectExecutor",
    "ClickHouseExecutor",
    "ExecutorError",
    "create_executor",
]

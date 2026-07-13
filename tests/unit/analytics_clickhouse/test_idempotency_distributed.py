"""Unit tests — distributed idempotency fix (r4-02).

Deterministic, no I/O: exercises `store._dedup_token`,
`store._executor_supports_dedup_token`, and `ClickHouseAnalyticsStore._append`'s
NEW unconditional-insert-then-read-back shape against the in-memory
`FakeClickHouseExecutor` (`analytics_clickhouse_factories.py`, itself updated
under r4-02 to simulate ClickHouse's real block-level dedup — see that
module's own docstring). A REAL-ClickHouse, truly-concurrent reproducer
(the actual r4-02 mission requirement: "≥20 concurrent writers, independent
executors") lives in `tests/integration/clickhouse/
test_idempotency_distributed.py`, which this module does not duplicate —
this module covers the DETERMINISTIC, always-runnable half of the fix
(token derivation correctness, compatibility-shim detection, and the
new `_append` control flow), not the live-container concurrency proof.
"""

from __future__ import annotations

import inspect
import threading

from analytics_clickhouse_factories import (
    TENANT_A,
    TENANT_B,
    FakeClickHouseExecutor,
    make_citation_row,
    make_experiment_registration_row,
    make_observation_row,
    new_fake_executor_with_tables,
)
from saena_analytics_clickhouse.store import (
    ClickHouseAnalyticsStore,
    _dedup_token,
    _executor_supports_dedup_token,
)


class TestDedupTokenDerivation:
    def test_same_inputs_always_derive_the_same_token(self) -> None:
        assert _dedup_token("observations", TENANT_A, "idem-1") == _dedup_token(
            "observations", TENANT_A, "idem-1"
        )

    def test_different_tenant_derives_a_different_token_for_the_same_key(self) -> None:
        """Proof the token is tenant-namespaced — same idempotency_key,
        different tenant_id, must never collide (r4-02 requirement)."""
        token_a = _dedup_token("observations", TENANT_A, "idem-shared")
        token_b = _dedup_token("observations", TENANT_B, "idem-shared")
        assert token_a != token_b

    def test_different_table_derives_a_different_token_for_the_same_tenant_and_key(self) -> None:
        token_obs = _dedup_token("observations", TENANT_A, "idem-1")
        token_cit = _dedup_token("citations", TENANT_A, "idem-1")
        assert token_obs != token_cit

    def test_different_idempotency_key_derives_a_different_token(self) -> None:
        token_1 = _dedup_token("observations", TENANT_A, "idem-1")
        token_2 = _dedup_token("observations", TENANT_A, "idem-2")
        assert token_1 != token_2

    def test_token_uses_a_delimiter_that_cannot_appear_in_a_valid_tenant_id(self) -> None:
        """`tenant_id` is DNS-safe-slug validated (identifiers.py) before
        `_dedup_token` is ever reached — the delimiter this function joins
        with must never be a character a valid tenant_id could contain,
        otherwise a crafted idempotency_key could in principle shift the
        (table, tenant_id) boundary. Documents the exact delimiter choice."""
        token = _dedup_token("observations", TENANT_A, "idem-1")
        assert "\x1f" in token
        assert TENANT_A in token.split("\x1f")


class TestExecutorSupportsDedupToken:
    def test_current_fake_executor_declares_dedup_token(self) -> None:
        assert _executor_supports_dedup_token(FakeClickHouseExecutor()) is True

    def test_pre_r4_02_shaped_executor_is_detected_as_unsupported(self) -> None:
        """A duck-typed executor whose `insert_rows` predates r4-02 (exact
        3-positional-arg shape, no `dedup_token`) — mirrors the OUT-OF-SCOPE
        `tests/integration/intelligence_failure/intelligence_failure_
        factories.py` fakes this fix must remain compatible with, without
        importing that module (outside this patch unit's exclusive write
        paths)."""

        class _LegacyExecutor:
            def execute(self, sql: str, params: dict | None = None) -> None:  # noqa: ANN001
                pass

            def query(self, sql: str, params: dict | None = None) -> list:  # noqa: ANN001
                return []

            def insert_rows(self, table: str, columns, rows) -> None:  # noqa: ANN001
                pass

        assert _executor_supports_dedup_token(_LegacyExecutor()) is False

    def test_store_against_a_legacy_executor_still_appends_without_raising(self) -> None:
        """Compatibility path end-to-end: a store built over a
        dedup-token-unaware executor still functions — single-writer
        append/get round-trips exactly like before r4-02 (it just cannot
        exercise the NEW race-free guarantee, documented in `executor.py`'s
        module docstring)."""

        class _LegacyExecutor:
            def __init__(self) -> None:
                self.rows: list[dict] = []

            def execute(self, sql: str, params: dict | None = None) -> None:  # noqa: ANN001
                pass

            def query(self, sql: str, params: dict | None = None) -> list:  # noqa: ANN001
                params = params or {}
                token = params.get("tenant_id")
                key = None
                for k, v in params.items():
                    if k.startswith("eq_idempotency_key_"):
                        key = v
                matches = [
                    r
                    for r in self.rows
                    if r.get("tenant_id") == token
                    and (key is None or r.get("idempotency_key") == key)
                ]
                if "dedup_witness" in sql:
                    return [(r.get("dedup_witness"),) for r in matches]
                return [(r.get("id"),) for r in matches]

            def insert_rows(self, table: str, columns, rows) -> None:  # noqa: ANN001
                for values in rows:
                    self.rows.append(dict(zip(columns, values, strict=True)))

        store = ClickHouseAnalyticsStore(_LegacyExecutor())
        row = make_observation_row()
        assert store.append_observation(row) is True


class TestAppendIsUnconditionalNoPreCheck:
    def test_append_never_calls_query_before_insert_rows(self) -> None:
        """Structural proof the r4-02 defect (check-then-insert) is gone:
        `_append` must not issue any `query()` call before its single
        `insert_rows()` call — only AFTER, for the read-back that determines
        the return value. A pre-insert existence check would show up as a
        `query()` call recorded before the `insert_rows()` call in the
        executor's own call order."""
        executor = new_fake_executor_with_tables()
        call_order: list[str] = []
        original_query = executor.query
        original_insert = executor.insert_rows

        def _tracked_query(sql, params=None):  # noqa: ANN001
            call_order.append("query")
            return original_query(sql, params)

        def _tracked_insert(table, columns, rows, *, dedup_token=None):  # noqa: ANN001
            call_order.append("insert_rows")
            return original_insert(table, columns, rows, dedup_token=dedup_token)

        executor.query = _tracked_query  # type: ignore[method-assign]
        executor.insert_rows = _tracked_insert  # type: ignore[method-assign]

        store = ClickHouseAnalyticsStore(executor)
        store.append_observation(make_observation_row())

        assert "insert_rows" in call_order
        first_insert_index = call_order.index("insert_rows")
        # No `query` call precedes the first (and only) `insert_rows` call —
        # the read-back query, if present, only ever comes AFTER.
        assert "query" not in call_order[:first_insert_index]

    def test_get_observations_signature_still_requires_tenant_id_positionally(self) -> None:
        """r4-02 must not weaken the pre-existing structural tenant
        injection guarantee (query.py) — unrelated invariant, checked here
        as a regression guard since this patch unit touches `store.py`."""
        sig = inspect.signature(ClickHouseAnalyticsStore.get_observations)
        params = list(sig.parameters.values())
        assert params[1].name == "tenant_id"
        assert params[1].default is inspect.Parameter.empty


class TestConcurrentAppendAgainstFakeExecutor:
    """Real Python threads racing `append_*` against ONE shared
    `FakeClickHouseExecutor` instance — not a substitute for the real-container
    reproducer (`tests/integration/clickhouse/test_idempotency_distributed.py`),
    but still a genuine `threading` race (GIL-interleaved, not serialized by
    test structure) proving `_append`'s NEW shape has no client-side critical
    section a duplicate can slip through, down to the fake's own
    `insert_rows`-level lock."""

    def test_twenty_concurrent_threads_same_event_yield_exactly_one_physical_row(
        self,
    ) -> None:
        executor = new_fake_executor_with_tables()
        store = ClickHouseAnalyticsStore(executor)
        row = make_observation_row(id="obs-race", idempotency_key="idem-race")
        results: list[bool] = []
        results_lock = threading.Lock()

        def _writer() -> None:
            outcome = store.append_observation(row)
            with results_lock:
                results.append(outcome)

        threads = [threading.Thread(target=_writer) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(executor.tables["observations"]) == 1
        assert sum(1 for r in results if r) == 1
        assert sum(1 for r in results if not r) == 19

    def test_concurrent_different_tenants_same_key_both_land(self) -> None:
        executor = new_fake_executor_with_tables()
        store = ClickHouseAnalyticsStore(executor)
        row_a = make_observation_row(tenant_id=TENANT_A, id="obs-a", idempotency_key="idem-shared")
        row_b = make_observation_row(tenant_id=TENANT_B, id="obs-b", idempotency_key="idem-shared")

        def _writer(row) -> None:  # noqa: ANN001
            store.append_observation(row)

        threads = [
            threading.Thread(target=_writer, args=(row_a,)),
            threading.Thread(target=_writer, args=(row_b,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(executor.tables["observations"]) == 2
        assert store.get_observations(TENANT_A)[0].id == "obs-a"
        assert store.get_observations(TENANT_B)[0].id == "obs-b"

    def test_concurrent_append_citation_and_experiment_registration_also_dedup(self) -> None:
        executor = new_fake_executor_with_tables()
        store = ClickHouseAnalyticsStore(executor)

        citation = make_citation_row(id="cit-race", idempotency_key="idem-cit-race")
        registration = make_experiment_registration_row(
            id="exp-race", idempotency_key="idem-exp-race"
        )

        def _write_citation() -> None:
            store.append_citation(citation)

        def _write_registration() -> None:
            store.append_experiment_registration(registration)

        citation_threads = [threading.Thread(target=_write_citation) for _ in range(20)]
        registration_threads = [threading.Thread(target=_write_registration) for _ in range(20)]
        for t in (*citation_threads, *registration_threads):
            t.start()
        for t in (*citation_threads, *registration_threads):
            t.join()

        assert len(executor.tables["citations"]) == 1
        assert len(executor.tables["experiment_registrations"]) == 1

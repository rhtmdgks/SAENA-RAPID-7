"""Integration tests — REAL ClickHouse, distributed idempotency (r4-02).

Docker unavailable / `clickhouse-connect` not installed -> every test in
this module is skipped with an honest, distinct reason
(`conftest.py::pytest_collection_modifyitems`), never silently passed.

Structure:

- `TestOldImplementationRaces` — pins the PRE-FIX check-then-insert shape
  (`_exists_idempotency_key` then `insert_rows`, exactly as `store.py`
  looked before r4-02) and proves it duplicates under real concurrent
  writers against a real ClickHouse container. This class is a PERMANENT
  regression witness — it is not deleted now that the fix has landed; it
  documents, executably, exactly what the defect was and that this test
  suite would have caught it.
- `TestFixedImplementationDoesNotRace` — the SAME concurrency shape against
  the CURRENT `ClickHouseAnalyticsStore.append_observation`/`append_citation`/
  `append_experiment_registration`, proving zero logical duplicates across
  all three owned tables, cross-tenant non-collision, and a crash/retry/resend
  scenario.

Every concurrent-writer test below constructs its OWN, independent
`ClickHouseConnectExecutor` (a fresh `clickhouse_connect.get_client(...)`) per
thread/writer — never one shared executor instance handed to N threads —
this is what "independent executors" in the r4-02 mission means: a fresh
TCP/HTTP connection per writer, exactly what two different intelligence-worker
PROCESSES would each hold in production, not just two calls sharing one
client's internal connection pool.
"""

from __future__ import annotations

import datetime as dt
import threading
from typing import Any

import pytest
from saena_analytics_clickhouse.errors import AnalyticsClickHouseError
from saena_analytics_clickhouse.executor import ClickHouseConnectExecutor
from saena_analytics_clickhouse.query import AnalyticsQuery, build_insert_columns
from saena_analytics_clickhouse.query_privacy import QuerySigningKeyRef, derive_query_ref
from saena_analytics_clickhouse.rows import CitationRow, ExperimentRegistrationRow, ObservationRow
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore

pytestmark = pytest.mark.integration

TENANT_A = "acme-co"
TENANT_B = "globex-co"

_WRITER_COUNT = 20

# `derive_query_ref` (independent-critic MUST-FIX round 2) is now KEYED and
# fail-closed — same duplicated-constant convention as `test_clickhouse_
# store.py`/`conftest.py` in this directory (never `from conftest import
# ...`, see that test module's own comment for the collision rationale).
_TEST_SIGNING_KEY_ENV_VAR = "SAENA_ANALYTICS_QUERY_SIGNING_KEY__INTEGRATION_TEST_FIXTURE"
_TEST_SIGNING_KEY_REF = QuerySigningKeyRef(env_var=_TEST_SIGNING_KEY_ENV_VAR)


def _observation(**overrides: Any) -> ObservationRow:
    tenant_id = overrides.get("tenant_id", TENANT_A)
    fields: dict[str, Any] = {
        "tenant_id": tenant_id,
        "id": "obs-race",
        "idempotency_key": "idem-race",
        "occurred_at": dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        "engine_id": "chatgpt-search",
        "run_id": "run-race",
        "query_ref": derive_query_ref(
            tenant_id=tenant_id,
            raw_query="best crm for startups",
            signing_key_ref=_TEST_SIGNING_KEY_REF,
        ).query_ref,
        "citation_refs": ("ref://citation/1",),
        "raw_object_ref": "ref://object/1",
    }
    fields.update(overrides)
    return ObservationRow(**fields)


def _citation(**overrides: Any) -> CitationRow:
    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "id": "cit-race",
        "idempotency_key": "idem-cit-race",
        "occurred_at": dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        "run_id": "run-race",
        "observation_id": "obs-race",
        "citation_ref": "ref://citation/1",
        "source_domain": "example.com",
        "contribution_score": 0.5,
    }
    fields.update(overrides)
    return CitationRow(**fields)


def _experiment_registration(**overrides: Any) -> ExperimentRegistrationRow:
    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "id": "exp-race",
        "idempotency_key": "idem-exp-race",
        "occurred_at": dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        "engine_id": "chatgpt-search",
        "locale": "en-US",
        "observation_cell": "cell-1",
        "registration_hash": "sha256:abc123",
        "status": "registered",
    }
    fields.update(overrides)
    return ExperimentRegistrationRow(**fields)


def _independent_executor(clickhouse_container: object) -> ClickHouseConnectExecutor:
    """A BRAND NEW `clickhouse_connect` client/connection — never shared
    with any other caller. This is the "independent executor instance" the
    r4-02 mission requires: a fresh connection per writer, not N callers
    sharing one client's connection pool."""
    import clickhouse_connect

    client = clickhouse_connect.get_client(
        host=clickhouse_container.get_container_host_ip(),  # type: ignore[attr-defined]
        port=int(clickhouse_container.get_exposed_port(8123)),  # type: ignore[attr-defined]
        username=clickhouse_container.username,  # type: ignore[attr-defined]
        password=clickhouse_container.password,  # type: ignore[attr-defined]
        database=clickhouse_container.dbname,  # type: ignore[attr-defined]
    )
    return ClickHouseConnectExecutor(client)


# --- OLD implementation, pinned verbatim (permanent regression witness) -----------
#
# EXACT shape of `ClickHouseAnalyticsStore._append`/`_exists_idempotency_key`
# BEFORE r4-02 (see git history / the r4-02 report for the removed code) —
# reproduced here, not imported (the real module no longer contains this
# shape), so this class keeps proving the DEFECT duplicates even after the
# fix has permanently replaced the production code path.


def _old_exists_idempotency_key(
    executor: ClickHouseConnectExecutor, table: str, tenant_id: str, idempotency_key: str
) -> bool:
    query = AnalyticsQuery.for_tenant(table, tenant_id).filter_eq(
        "idempotency_key", idempotency_key
    )
    sql, params = query.to_select_sql(columns=("id",))
    return len(executor.query(sql, params)) > 0


def _old_append(executor: ClickHouseConnectExecutor, table: str, row: ObservationRow) -> bool:
    """Textbook check-then-insert TOCTOU race — the r4-02 defect."""
    if _old_exists_idempotency_key(executor, table, row.tenant_id, row.idempotency_key):
        return False
    fields_map = {
        "tenant_id": row.tenant_id,
        "id": row.id,
        "idempotency_key": row.idempotency_key,
        "occurred_at": row.occurred_at,
        "engine_id": row.engine_id,
        "run_id": row.run_id,
        "query_ref": row.query_ref,
        "query_digest": row.query_digest,
        "citation_refs": list(row.citation_refs),
        "raw_object_ref": row.raw_object_ref,
        "dedup_witness": "",
    }
    columns, values = build_insert_columns(table, fields_map)
    executor.insert_rows(table, columns, [values])
    return True


class TestOldImplementationRaces:
    """Permanent regression witness — proves the PRE-r4-02 check-then-insert
    shape duplicates under real concurrent writers. Kept forever, not
    deleted once the fix landed (module docstring)."""

    def test_old_check_then_insert_shape_duplicates_under_concurrent_writers(
        self, clickhouse_container: object, executor: ClickHouseConnectExecutor
    ) -> None:
        row = _observation(id="obs-old-race", idempotency_key="idem-old-race")
        barrier = threading.Barrier(_WRITER_COUNT)

        def _writer() -> None:
            writer_executor = _independent_executor(clickhouse_container)
            barrier.wait()  # maximize actual concurrent overlap
            _old_append(writer_executor, "observations", row)

        threads = [threading.Thread(target=_writer) for _ in range(_WRITER_COUNT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        sql, params = (
            AnalyticsQuery.for_tenant("observations", TENANT_A)
            .filter_eq("idempotency_key", "idem-old-race")
            .to_select_sql(columns=("id",))
        )
        rows = executor.query(sql, params)
        # THE DEFECT: with the old check-then-insert shape, real concurrent
        # writers routinely land MORE than one physical row for the exact
        # same (tenant_id, idempotency_key) — MergeTree enforces no UNIQUE
        # constraint, so nothing stops it. This assertion documents the
        # observed old-implementation failure (>= 2, not == 1) — it is
        # EXPECTED to be flaky-high (concurrency-dependent exact count) but
        # the defect is that it is essentially never reliably 1 under load
        # of this width; a single run reliably reproducing > 1 is the
        # reproducer requirement.
        assert len(rows) > 1, (
            "expected the OLD check-then-insert implementation to duplicate under "
            f"{_WRITER_COUNT} concurrent writers (reproducer) — got {len(rows)} row(s); "
            "if this ever reads exactly 1, the environment's scheduler happened to "
            "fully serialize every writer this run (not a guarantee the race is closed)"
        )


# --- Current (fixed) implementation --------------------------------------------------


class TestFixedImplementationDoesNotRace:
    def test_twenty_independent_writers_same_observation_yield_one_logical_row(
        self, clickhouse_container: object
    ) -> None:
        row = _observation(id="obs-fixed-race", idempotency_key="idem-fixed-race")
        barrier = threading.Barrier(_WRITER_COUNT)
        outcomes: list[bool] = []
        outcomes_lock = threading.Lock()

        def _writer() -> None:
            store = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
            barrier.wait()
            outcome = store.append_observation(row)
            with outcomes_lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=_writer) for _ in range(_WRITER_COUNT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        verifier = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
        results = verifier.get_observations(TENANT_A)
        matching = [r for r in results if r.idempotency_key == "idem-fixed-race"]
        assert len(matching) == 1, (
            f"expected exactly 1 LOGICAL row for idem-fixed-race after "
            f"{_WRITER_COUNT} concurrent independent writers, got {len(matching)}"
        )
        # Physical uniqueness ALSO holds here (within the dedup window,
        # store.py module docstring "Physical vs logical") — a direct COUNT
        # confirms no second physical row exists either, not merely that the
        # first one happens to be returned by a LIMIT-less SELECT.
        raw_count = verifier._executor.query(  # noqa: SLF001 - white-box physical-count check
            "SELECT count() FROM observations WHERE tenant_id = %(t)s AND idempotency_key = %(k)s",
            {"t": TENANT_A, "k": "idem-fixed-race"},
        )
        assert raw_count[0][0] == 1

    def test_twenty_independent_writers_same_citation_yield_one_logical_row(
        self, clickhouse_container: object
    ) -> None:
        row = _citation(id="cit-fixed-race", idempotency_key="idem-cit-fixed-race")
        barrier = threading.Barrier(_WRITER_COUNT)

        def _writer() -> None:
            store = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
            barrier.wait()
            store.append_citation(row)

        threads = [threading.Thread(target=_writer) for _ in range(_WRITER_COUNT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        verifier = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
        matching = [
            r
            for r in verifier.get_citations(TENANT_A)
            if r.idempotency_key == "idem-cit-fixed-race"
        ]
        assert len(matching) == 1

    def test_twenty_independent_writers_same_experiment_registration_yield_one_logical_row(
        self, clickhouse_container: object
    ) -> None:
        row = _experiment_registration(id="exp-fixed-race", idempotency_key="idem-exp-fixed-race")
        barrier = threading.Barrier(_WRITER_COUNT)

        def _writer() -> None:
            store = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
            barrier.wait()
            store.append_experiment_registration(row)

        threads = [threading.Thread(target=_writer) for _ in range(_WRITER_COUNT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        verifier = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
        matching = [
            r
            for r in verifier.get_experiment_registrations(TENANT_A)
            if r.idempotency_key == "idem-exp-fixed-race"
        ]
        assert len(matching) == 1

    def test_same_idempotency_key_different_tenants_does_not_collide_under_concurrency(
        self, clickhouse_container: object
    ) -> None:
        row_a = _observation(
            tenant_id=TENANT_A, id="obs-tenant-a", idempotency_key="idem-cross-tenant"
        )
        row_b = _observation(
            tenant_id=TENANT_B, id="obs-tenant-b", idempotency_key="idem-cross-tenant"
        )
        barrier = threading.Barrier(2 * _WRITER_COUNT)

        def _writer(row: ObservationRow) -> None:
            store = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
            barrier.wait()
            store.append_observation(row)

        threads = [
            threading.Thread(target=_writer, args=(row_a if i % 2 == 0 else row_b,))
            for i in range(2 * _WRITER_COUNT)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        verifier = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
        a_rows = [
            r
            for r in verifier.get_observations(TENANT_A)
            if r.idempotency_key == "idem-cross-tenant"
        ]
        b_rows = [
            r
            for r in verifier.get_observations(TENANT_B)
            if r.idempotency_key == "idem-cross-tenant"
        ]
        assert len(a_rows) == 1
        assert len(b_rows) == 1
        assert a_rows[0].id == "obs-tenant-a"
        assert b_rows[0].id == "obs-tenant-b"

    def test_crash_then_resend_retry_lands_exactly_one_row(
        self, clickhouse_container: object
    ) -> None:
        """Simulates a producer that crashes/times out AFTER its insert
        physically landed but BEFORE it observed the ack (a real at-least-once
        delivery scenario) and therefore resends the identical event later —
        the resend must be a no-op, never a second physical/logical row."""
        row = _observation(id="obs-crash-retry", idempotency_key="idem-crash-retry")

        first_store = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
        first_outcome = first_store.append_observation(row)
        assert first_outcome is True

        # Resend: a DIFFERENT executor/connection (simulates a new process
        # instance after the crash), same row, sent 3 times (over-eager retry).
        for _ in range(3):
            retry_store = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
            outcome = retry_store.append_observation(row)
            assert outcome is False

        verifier = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
        matching = [
            r
            for r in verifier.get_observations(TENANT_A)
            if r.idempotency_key == "idem-crash-retry"
        ]
        assert len(matching) == 1

    def test_append_return_value_is_true_for_first_observed_writer_only(
        self, clickhouse_container: object
    ) -> None:
        """Honest return-value semantics (store.py docstring): across N
        concurrent writers for the SAME (tenant_id, idempotency_key), exactly
        ONE call observes itself as the first-observed writer (`True`) — the
        rest observe `False`, never an exception, never all-`True`."""
        row = _observation(id="obs-return-value", idempotency_key="idem-return-value")
        barrier = threading.Barrier(_WRITER_COUNT)
        outcomes: list[bool] = []
        outcomes_lock = threading.Lock()

        def _writer() -> None:
            store = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
            barrier.wait()
            outcome = store.append_observation(row)
            with outcomes_lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=_writer) for _ in range(_WRITER_COUNT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(outcomes) == _WRITER_COUNT
        assert sum(1 for o in outcomes if o) == 1
        assert sum(1 for o in outcomes if not o) == _WRITER_COUNT - 1

    def test_append_never_raises_under_concurrent_duplicate_writers(
        self, clickhouse_container: object
    ) -> None:
        row = _observation(id="obs-no-raise", idempotency_key="idem-no-raise")
        barrier = threading.Barrier(_WRITER_COUNT)
        errors: list[BaseException] = []
        errors_lock = threading.Lock()

        def _writer() -> None:
            try:
                store = ClickHouseAnalyticsStore(_independent_executor(clickhouse_container))
                barrier.wait()
                store.append_observation(row)
            except AnalyticsClickHouseError as exc:  # pragma: no cover - failure path
                with errors_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=_writer) for _ in range(_WRITER_COUNT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

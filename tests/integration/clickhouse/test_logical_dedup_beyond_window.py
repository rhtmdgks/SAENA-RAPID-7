"""r4-02 follow-on (real ClickHouse): query-time LOGICAL dedup is UNCONDITIONAL,
independent of the physical `non_replicated_deduplication_window`.

Method: create the three tables with `deduplication_window = 1` (only the LAST
inserted block's dedup token is remembered), then for each table:
  1. insert the original event,
  2. insert a DIFFERENT event (a new block → evicts the original's token from
     the size-1 window),
  3. replay the original (same dedup token) — now OUTSIDE the window, so it is
     NOT physically deduplicated and lands as a SECOND physical row.
Then prove the physical duplicate exists (`count()` == 2) but every `get_*`
returns EXACTLY ONE logical row. Also covers cross-tenant, time-range,
pagination, and the same-key/different-payload collision policy.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from saena_analytics_clickhouse.executor import ClickHouseConnectExecutor
from saena_analytics_clickhouse.query_privacy import QuerySigningKeyRef, derive_query_ref
from saena_analytics_clickhouse.rows import CitationRow, ExperimentRegistrationRow, ObservationRow
from saena_analytics_clickhouse.schema import (
    TABLE_NAMES,
    create_table_statements,
    migrate_up,
)
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore

TENANT_A = "acme-co"
TENANT_B = "globex-co"
_KEY_REF = QuerySigningKeyRef(env_var="SAENA_ANALYTICS_QUERY_SIGNING_KEY__INTEGRATION_TEST_FIXTURE")
_T0 = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)


def _obs(**over: Any) -> ObservationRow:
    tenant_id = over.get("tenant_id", TENANT_A)
    fields: dict[str, Any] = {
        "tenant_id": tenant_id,
        "id": "obs-0",
        "idempotency_key": "idem-obs",
        "occurred_at": _T0,
        "engine_id": "chatgpt-search",
        "run_id": "run-1",
        "query_ref": derive_query_ref(
            tenant_id=tenant_id, raw_query="best crm", signing_key_ref=_KEY_REF
        ).query_ref,
        "citation_refs": ("ref://citation/1",),
        "raw_object_ref": "ref://object/1",
    }
    fields.update(over)
    return ObservationRow(**fields)


def _cit(**over: Any) -> CitationRow:
    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "id": "cit-0",
        "idempotency_key": "idem-cit",
        "occurred_at": _T0,
        "run_id": "run-1",
        "observation_id": "obs-0",
        "citation_ref": "ref://citation/1",
        "source_domain": "example.com",
        "contribution_score": 0.5,
    }
    fields.update(over)
    return CitationRow(**fields)


def _exp(**over: Any) -> ExperimentRegistrationRow:
    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "id": "exp-0",
        "idempotency_key": "idem-exp",
        "occurred_at": _T0,
        "engine_id": "chatgpt-search",
        "locale": "en-US",
        "observation_cell": "cell-1",
        "registration_hash": "sha256:abc",
        "status": "registered",
    }
    fields.update(over)
    return ExperimentRegistrationRow(**fields)


@pytest.fixture
def small_window_store(
    executor: ClickHouseConnectExecutor,
) -> Iterator[ClickHouseAnalyticsStore]:
    """Recreate the 3 tables with a physical dedup window of 1, then restore the
    production (window=1000) tables afterwards so other tests are unaffected."""
    for table in TABLE_NAMES:
        executor.execute(f"DROP TABLE IF EXISTS {table}")
    for ddl in create_table_statements(deduplication_window=1):
        executor.execute(ddl)
    try:
        yield ClickHouseAnalyticsStore(executor)
    finally:
        for table in TABLE_NAMES:
            executor.execute(f"DROP TABLE IF EXISTS {table}")
        migrate_up(executor)


def _physical_count(
    executor: ClickHouseConnectExecutor, table: str, tenant_id: str, idempotency_key: str
) -> int:
    rows = executor.query(
        f"SELECT count() FROM {table} WHERE tenant_id = %(t)s AND idempotency_key = %(k)s",
        {"t": tenant_id, "k": idempotency_key},
    )
    return int(rows[0][0])


def _force_physical_duplicate(store: ClickHouseAnalyticsStore, append, original, different) -> None:
    """original block → a DIFFERENT block (evicts original's token from the
    window=1) → replay original block (now outside the window → NOT deduped)."""
    append(original)
    append(different)
    append(original)


class TestObservationsLogicalDedupBeyondWindow:
    def test_physical_duplicate_exists_but_get_returns_one(
        self, small_window_store: ClickHouseAnalyticsStore, executor: ClickHouseConnectExecutor
    ) -> None:
        store = small_window_store
        _force_physical_duplicate(
            store,
            store.append_observation,
            _obs(id="obs-0", idempotency_key="idem-obs"),
            _obs(id="obs-x", idempotency_key="idem-other"),
        )
        # physical: the replay landed as a 2nd row (window=1 evicted the token).
        assert _physical_count(executor, "observations", TENANT_A, "idem-obs") == 2
        # logical: exactly one row for the duplicated key.
        got = [r for r in store.get_observations(TENANT_A) if r.idempotency_key == "idem-obs"]
        assert len(got) == 1
        assert got[0].id == "obs-0"


class TestCitationsLogicalDedupBeyondWindow:
    def test_physical_duplicate_exists_but_get_returns_one(
        self, small_window_store: ClickHouseAnalyticsStore, executor: ClickHouseConnectExecutor
    ) -> None:
        store = small_window_store
        _force_physical_duplicate(
            store,
            store.append_citation,
            _cit(id="cit-0", idempotency_key="idem-cit"),
            _cit(id="cit-x", idempotency_key="idem-other"),
        )
        assert _physical_count(executor, "citations", TENANT_A, "idem-cit") == 2
        got = [r for r in store.get_citations(TENANT_A) if r.idempotency_key == "idem-cit"]
        assert len(got) == 1
        assert got[0].id == "cit-0"


class TestExperimentRegistrationsLogicalDedupBeyondWindow:
    def test_physical_duplicate_exists_but_get_returns_one(
        self, small_window_store: ClickHouseAnalyticsStore, executor: ClickHouseConnectExecutor
    ) -> None:
        store = small_window_store
        _force_physical_duplicate(
            store,
            store.append_experiment_registration,
            _exp(id="exp-0", idempotency_key="idem-exp"),
            _exp(id="exp-x", idempotency_key="idem-other"),
        )
        assert _physical_count(executor, "experiment_registrations", TENANT_A, "idem-exp") == 2
        got = [
            r
            for r in store.get_experiment_registrations(TENANT_A)
            if r.idempotency_key == "idem-exp"
        ]
        assert len(got) == 1
        assert got[0].id == "exp-0"


class TestCrossTenantLogicalDedup:
    def test_same_idempotency_key_two_tenants_are_independent(
        self, small_window_store: ClickHouseAnalyticsStore, executor: ClickHouseConnectExecutor
    ) -> None:
        store = small_window_store
        # tenant A duplicated, tenant B a single row — SAME idempotency_key.
        _force_physical_duplicate(
            store,
            store.append_observation,
            _obs(tenant_id=TENANT_A, id="obs-a", idempotency_key="idem-shared"),
            _obs(tenant_id=TENANT_A, id="obs-a-other", idempotency_key="idem-other"),
        )
        store.append_observation(
            _obs(tenant_id=TENANT_B, id="obs-b", idempotency_key="idem-shared")
        )

        a = [r for r in store.get_observations(TENANT_A) if r.idempotency_key == "idem-shared"]
        b = [r for r in store.get_observations(TENANT_B) if r.idempotency_key == "idem-shared"]
        assert len(a) == 1 and a[0].id == "obs-a"
        assert len(b) == 1 and b[0].id == "obs-b"
        # no cross-tenant bleed: tenant B never sees tenant A's rows.
        assert all(r.tenant_id == TENANT_B for r in store.get_observations(TENANT_B))


class TestTimeRangeAndPaginationAfterDedup:
    def test_time_range_bounds_the_deduped_set(
        self, small_window_store: ClickHouseAnalyticsStore, executor: ClickHouseConnectExecutor
    ) -> None:
        store = small_window_store
        _force_physical_duplicate(
            store,
            store.append_observation,
            _obs(id="obs-in", idempotency_key="idem-in", occurred_at=_T0),
            _obs(id="obs-out", idempotency_key="idem-out", occurred_at=_T0 + dt.timedelta(days=10)),
        )
        start = _T0 - dt.timedelta(hours=1)
        end = _T0 + dt.timedelta(hours=1)
        got = store.get_observations(TENANT_A, start=start, end=end)
        assert [r.idempotency_key for r in got] == ["idem-in"]  # duplicate collapsed, range applied

    def test_pagination_limit_counts_distinct_logical_rows_not_duplicates(
        self, small_window_store: ClickHouseAnalyticsStore, executor: ClickHouseConnectExecutor
    ) -> None:
        store = small_window_store
        # three distinct keys, each physically duplicated beyond the window.
        for i in range(3):
            _force_physical_duplicate(
                store,
                store.append_observation,
                _obs(
                    id=f"obs-{i}",
                    idempotency_key=f"idem-{i}",
                    occurred_at=_T0 + dt.timedelta(minutes=i),
                ),
                _obs(id=f"obs-adv-{i}", idempotency_key=f"idem-adv-{i}"),
            )
        # 6 real keys total (3 primary + 3 advancers); limit must bound LOGICAL rows.
        limited = store.get_observations(TENANT_A, limit=2)
        assert len(limited) == 2
        # and every returned key is distinct (no physical duplicate surfaced).
        assert len({r.idempotency_key for r in limited}) == 2


class TestSameKeyDifferentPayloadCollisionPolicy:
    def test_collision_resolves_deterministically_to_minimal_id(
        self, small_window_store: ClickHouseAnalyticsStore, executor: ClickHouseConnectExecutor
    ) -> None:
        store = small_window_store
        # same (tenant, idempotency_key) but DIFFERENT id + payload, both landing
        # physically (the 2nd is beyond the window=1).
        store.append_observation(_obs(id="obs-bbb", idempotency_key="idem-collide", run_id="run-b"))
        store.append_observation(_obs(id="obs-adv", idempotency_key="idem-adv"))
        store.append_observation(_obs(id="obs-aaa", idempotency_key="idem-collide", run_id="run-a"))

        assert _physical_count(executor, "observations", TENANT_A, "idem-collide") == 2
        got = [r for r in store.get_observations(TENANT_A) if r.idempotency_key == "idem-collide"]
        # deterministic winner = lexicographically-minimal id ("obs-aaa"), every run.
        assert len(got) == 1
        assert got[0].id == "obs-aaa"
        assert got[0].run_id == "run-a"

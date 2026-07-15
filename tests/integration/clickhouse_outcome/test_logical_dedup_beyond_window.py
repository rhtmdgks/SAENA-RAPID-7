"""r4-02 pattern applied to `measurement_outcome` (w5-11, real ClickHouse):
query-time LOGICAL dedup is UNCONDITIONAL, independent of the physical
`non_replicated_deduplication_window` — mirrors `tests/integration/
clickhouse/test_logical_dedup_beyond_window.py`'s method exactly for the new
table.

Method: recreate `measurement_outcome` with `deduplication_window = 1`, then:
  1. insert the original event,
  2. insert a DIFFERENT event (a new block -> evicts the original's token
     from the size-1 window),
  3. replay the original (same dedup token) — now OUTSIDE the window, so it
     is NOT physically deduplicated and lands as a SECOND physical row.
Then prove the physical duplicate exists (`count()` == 2) but `get_*`/the
raw-vs-adjusted view return EXACTLY ONE logical row.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from saena_analytics_clickhouse.executor import ClickHouseConnectExecutor
from saena_analytics_clickhouse.rows import MeasurementOutcomeRow
from saena_analytics_clickhouse.schema import (
    TABLE_NAMES,
    create_table_statements,
    migrate_up,
)
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore

pytestmark = pytest.mark.integration

TENANT_A = "acme-co"
TENANT_B = "globex-co"
_T0 = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
_T1 = dt.datetime(2026, 7, 8, tzinfo=dt.UTC)


def _mo(**over: Any) -> MeasurementOutcomeRow:
    tenant_id = over.get("tenant_id", TENANT_A)
    fields: dict[str, Any] = {
        "tenant_id": tenant_id,
        "id": "mo-0",
        "idempotency_key": "idem-mo",
        "occurred_at": _T1,
        "experiment_id": "exp-1",
        "registration_canonical_hash": "sha256:" + "a" * 64,
        "window_started_at": _T0,
        "window_ended_at": _T1,
        "b_verdict": "pass",
        "reason_codes": ("two_independent_layers_confirmed",),
        "outcome_layer": "discovery",
        "sample_count_treatment": 128,
        "sample_count_control": 130,
        "insufficient_data": False,
        "evidence_bundle_manifest_hash": "sha256:" + "b" * 64,
        "grs_policy_version": "grs-v1",
        "grs_policy_hash": "sha256:" + "c" * 64,
        "grs_policy_provenance": "policy://grs/window-fixture",
        "evidence_basis_id": "sha256:" + "d" * 64,
        "net_of_control_lift": 0.12,
        "raw_lift": 0.15,
    }
    fields.update(over)
    return MeasurementOutcomeRow(**fields)


@pytest.fixture
def small_window_store(
    executor: ClickHouseConnectExecutor,
) -> Iterator[ClickHouseAnalyticsStore]:
    """Recreate all 4 tables with a physical dedup window of 1, then restore
    the production (window=1000) tables afterwards so other tests are
    unaffected — mirrors the sibling fixture in `tests/integration/
    clickhouse/test_logical_dedup_beyond_window.py` (all tables, not just
    `measurement_outcome`, since `create_table_statements` returns the full
    set and `migrate_up` restores the full set on teardown)."""
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
    executor: ClickHouseConnectExecutor, tenant_id: str, idempotency_key: str
) -> int:
    rows = executor.query(
        "SELECT count() FROM measurement_outcome WHERE tenant_id = %(t)s "
        "AND idempotency_key = %(k)s",
        {"t": tenant_id, "k": idempotency_key},
    )
    return int(rows[0][0])


def _force_physical_duplicate(store: ClickHouseAnalyticsStore, original, different) -> None:
    """original block -> a DIFFERENT block (evicts original's token from the
    window=1) -> replay original block (now outside the window -> NOT
    deduped)."""
    store.append_measurement_outcome(original)
    store.append_measurement_outcome(different)
    store.append_measurement_outcome(original)


class TestMeasurementOutcomeLogicalDedupBeyondWindow:
    def test_physical_duplicate_exists_but_get_returns_one(
        self, small_window_store: ClickHouseAnalyticsStore, executor: ClickHouseConnectExecutor
    ) -> None:
        store = small_window_store
        _force_physical_duplicate(
            store,
            _mo(id="mo-0", idempotency_key="idem-mo"),
            _mo(id="mo-x", idempotency_key="idem-other"),
        )
        # physical: the replay landed as a 2nd row (window=1 evicted the token).
        assert _physical_count(executor, TENANT_A, "idem-mo") == 2
        # logical: exactly one row for the duplicated key.
        got = [
            r for r in store.get_measurement_outcomes(TENANT_A) if r.idempotency_key == "idem-mo"
        ]
        assert len(got) == 1
        assert got[0].id == "mo-0"

    def test_raw_vs_adjusted_view_also_collapses_the_physical_duplicate(
        self, small_window_store: ClickHouseAnalyticsStore, executor: ClickHouseConnectExecutor
    ) -> None:
        store = small_window_store
        _force_physical_duplicate(
            store,
            _mo(id="mo-0", idempotency_key="idem-mo", experiment_id="exp-dedup"),
            _mo(id="mo-x", idempotency_key="idem-other"),
        )
        assert _physical_count(executor, TENANT_A, "idem-mo") == 2
        view = store.get_measurement_outcome_raw_vs_adjusted_view(
            TENANT_A, experiment_id="exp-dedup"
        )
        assert len(view) == 1


class TestCrossTenantLogicalDedup:
    def test_same_idempotency_key_two_tenants_are_independent(
        self, small_window_store: ClickHouseAnalyticsStore, executor: ClickHouseConnectExecutor
    ) -> None:
        store = small_window_store
        _force_physical_duplicate(
            store,
            _mo(tenant_id=TENANT_A, id="mo-a", idempotency_key="idem-shared"),
            _mo(tenant_id=TENANT_A, id="mo-a-other", idempotency_key="idem-other"),
        )
        store.append_measurement_outcome(
            _mo(tenant_id=TENANT_B, id="mo-b", idempotency_key="idem-shared")
        )

        a = [
            r
            for r in store.get_measurement_outcomes(TENANT_A)
            if r.idempotency_key == "idem-shared"
        ]
        b = [
            r
            for r in store.get_measurement_outcomes(TENANT_B)
            if r.idempotency_key == "idem-shared"
        ]
        assert len(a) == 1 and a[0].id == "mo-a"
        assert len(b) == 1 and b[0].id == "mo-b"
        assert all(r.tenant_id == TENANT_B for r in store.get_measurement_outcomes(TENANT_B))


class TestSameKeyDifferentPayloadCollisionPolicy:
    def test_collision_resolves_deterministically_to_minimal_id(
        self, small_window_store: ClickHouseAnalyticsStore, executor: ClickHouseConnectExecutor
    ) -> None:
        store = small_window_store
        store.append_measurement_outcome(
            _mo(id="mo-bbb", idempotency_key="idem-collide", experiment_id="exp-b")
        )
        store.append_measurement_outcome(_mo(id="mo-adv", idempotency_key="idem-adv"))
        store.append_measurement_outcome(
            _mo(id="mo-aaa", idempotency_key="idem-collide", experiment_id="exp-a")
        )

        assert _physical_count(executor, TENANT_A, "idem-collide") == 2
        got = [
            r
            for r in store.get_measurement_outcomes(TENANT_A)
            if r.idempotency_key == "idem-collide"
        ]
        # deterministic winner = lexicographically-minimal id ("mo-aaa"), every run.
        assert len(got) == 1
        assert got[0].id == "mo-aaa"
        assert got[0].experiment_id == "exp-a"

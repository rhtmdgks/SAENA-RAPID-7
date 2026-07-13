"""Integration tests — `measurement_outcome` append/get against a REAL
ClickHouse container (w5-11; mirrors `tests/integration/clickhouse/
test_clickhouse_store.py`'s own structure for the w4-06 tables).

Docker unavailable / `clickhouse-connect` not installed -> every test in this
module is skipped with an honest, distinct reason
(`conftest.py::pytest_collection_modifyitems`), never silently passed.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from saena_analytics_clickhouse.rows import MeasurementOutcomeRow
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore

pytestmark = pytest.mark.integration

TENANT_A = "acme-co"
TENANT_B = "globex-co"

_WINDOW_START = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
_WINDOW_END = dt.datetime(2026, 7, 8, tzinfo=dt.UTC)


def _measurement_outcome(**overrides: Any) -> MeasurementOutcomeRow:
    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "id": "mo-1",
        "idempotency_key": "idem-mo-1",
        "occurred_at": _WINDOW_END,
        "experiment_id": "exp-1",
        "registration_canonical_hash": "sha256:" + "a" * 64,
        "window_started_at": _WINDOW_START,
        "window_ended_at": _WINDOW_END,
        "b_verdict": "pass",
        "reason_codes": ("two_independent_layers_confirmed",),
        "outcome_layer": "discovery",
        "sample_count_treatment": 128,
        "sample_count_control": 130,
        "insufficient_data": False,
        "evidence_bundle_manifest_hash": "sha256:" + "b" * 64,
        "grs_policy_version": "grs-v1",
        "grs_policy_hash": "sha256:" + "c" * 64,
        "grs_policy_provenance": "policy://grs/integration-fixture",
        "evidence_basis_id": "sha256:" + "d" * 64,
        "net_of_control_lift": 0.12,
        "raw_lift": 0.15,
    }
    fields.update(overrides)
    return MeasurementOutcomeRow(**fields)


class TestAppendRoundTrip:
    def test_append_then_get_round_trips(self, store: ClickHouseAnalyticsStore) -> None:
        row = _measurement_outcome()
        assert store.append_measurement_outcome(row) is True
        (fetched,) = store.get_measurement_outcomes(TENANT_A)
        assert fetched.id == row.id
        assert fetched.experiment_id == row.experiment_id
        assert fetched.b_verdict == row.b_verdict
        assert fetched.reason_codes == row.reason_codes
        assert fetched.outcome_layer == row.outcome_layer
        assert fetched.net_of_control_lift == row.net_of_control_lift
        assert fetched.raw_lift == row.raw_lift
        assert fetched.evidence_basis_id == row.evidence_basis_id
        assert fetched.window_started_at == row.window_started_at
        assert fetched.window_ended_at == row.window_ended_at

    def test_null_lift_and_evidence_basis_round_trip_as_none(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = _measurement_outcome(
            evidence_basis_id=None,
            net_of_control_lift=None,
            raw_lift=None,
            insufficient_data=True,
            b_verdict="undetermined",
        )
        store.append_measurement_outcome(row)
        (fetched,) = store.get_measurement_outcomes(TENANT_A)
        assert fetched.evidence_basis_id is None
        assert fetched.net_of_control_lift is None
        assert fetched.raw_lift is None
        assert fetched.b_verdict == "undetermined"


class TestDedupReplay:
    def test_duplicate_idempotency_key_replay_is_a_no_op(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = _measurement_outcome()
        assert store.append_measurement_outcome(row) is True
        assert store.append_measurement_outcome(row) is False
        assert len(store.get_measurement_outcomes(TENANT_A)) == 1

    def test_duplicate_replay_across_multiple_attempts_stays_single_row(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = _measurement_outcome()
        for _ in range(3):
            store.append_measurement_outcome(row)
        assert len(store.get_measurement_outcomes(TENANT_A)) == 1


class TestPhysicalDuplicateCollapsesToLogicalOne:
    def test_two_concurrent_style_appends_of_the_same_row_still_read_back_one(
        self, store: ClickHouseAnalyticsStore, executor: object
    ) -> None:
        """A same-token repeated `insert_rows` call (this is what
        `append_measurement_outcome` always issues, r4-02) is deduplicated by
        ClickHouse's own server-side block dedup WITHIN the production
        window — proves the physical single-row outcome directly, the query-
        time logical-dedup-BEYOND-the-window case is covered by
        `test_logical_dedup_beyond_window.py` in this same directory."""
        row = _measurement_outcome()
        store.append_measurement_outcome(row)
        store.append_measurement_outcome(row)
        rows = executor.query(
            "SELECT count() FROM measurement_outcome WHERE tenant_id = %(t)s "
            "AND idempotency_key = %(k)s",
            {"t": TENANT_A, "k": row.idempotency_key},
        )
        assert int(rows[0][0]) == 1


class TestCrossTenantIsolation:
    def test_get_measurement_outcomes_never_returns_another_tenants_rows(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        store.append_measurement_outcome(_measurement_outcome(tenant_id=TENANT_A, id="mo-a"))
        store.append_measurement_outcome(
            _measurement_outcome(tenant_id=TENANT_B, id="mo-b", idempotency_key="idem-b")
        )
        assert {row.id for row in store.get_measurement_outcomes(TENANT_A)} == {"mo-a"}
        assert {row.id for row in store.get_measurement_outcomes(TENANT_B)} == {"mo-b"}

    def test_same_idempotency_key_different_tenants_both_land(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        store.append_measurement_outcome(
            _measurement_outcome(
                tenant_id=TENANT_A, id="mo-shared-a", idempotency_key="idem-shared"
            )
        )
        store.append_measurement_outcome(
            _measurement_outcome(
                tenant_id=TENANT_B, id="mo-shared-b", idempotency_key="idem-shared"
            )
        )
        assert len(store.get_measurement_outcomes(TENANT_A)) == 1
        assert len(store.get_measurement_outcomes(TENANT_B)) == 1

    def test_raw_vs_adjusted_view_never_returns_another_tenants_rows(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        store.append_measurement_outcome(_measurement_outcome(tenant_id=TENANT_A, id="mo-a"))
        store.append_measurement_outcome(
            _measurement_outcome(tenant_id=TENANT_B, id="mo-b", idempotency_key="idem-b")
        )
        view_a = store.get_measurement_outcome_raw_vs_adjusted_view(TENANT_A)
        view_b = store.get_measurement_outcome_raw_vs_adjusted_view(TENANT_B)
        assert all(r.tenant_id == TENANT_A for r in view_a)
        assert all(r.tenant_id == TENANT_B for r in view_b)


class TestRawVsAdjustedView:
    def test_view_projects_both_lift_figures_from_a_real_container(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        store.append_measurement_outcome(
            _measurement_outcome(net_of_control_lift=0.12, raw_lift=0.20)
        )
        (view_row,) = store.get_measurement_outcome_raw_vs_adjusted_view(TENANT_A)
        assert view_row.raw_lift == 0.20
        assert view_row.net_of_control_lift == 0.12

    def test_view_filters_by_experiment_id(self, store: ClickHouseAnalyticsStore) -> None:
        store.append_measurement_outcome(
            _measurement_outcome(id="mo-a", idempotency_key="idem-a", experiment_id="exp-a")
        )
        store.append_measurement_outcome(
            _measurement_outcome(id="mo-b", idempotency_key="idem-b", experiment_id="exp-b")
        )
        results = store.get_measurement_outcome_raw_vs_adjusted_view(
            TENANT_A, experiment_id="exp-a"
        )
        assert {r.experiment_id for r in results} == {"exp-a"}

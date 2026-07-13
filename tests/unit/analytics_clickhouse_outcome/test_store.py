"""Unit tests for `ClickHouseAnalyticsStore.append_measurement_outcome` /
`get_measurement_outcomes` / `get_measurement_outcome_raw_vs_adjusted_view`
(w5-11) — in-memory `FakeClickHouseExecutor` seam, no I/O."""

from __future__ import annotations

import datetime as dt

from analytics_clickhouse_outcome_factories import (
    TENANT_A,
    TENANT_B,
    FakeClickHouseExecutor,
    make_measurement_outcome_row,
)
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore


class TestAppendIdempotency:
    def test_append_returns_true_on_first_insert(self, store: ClickHouseAnalyticsStore) -> None:
        assert store.append_measurement_outcome(make_measurement_outcome_row()) is True

    def test_append_returns_false_on_duplicate_idempotency_key(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = make_measurement_outcome_row()
        assert store.append_measurement_outcome(row) is True
        assert store.append_measurement_outcome(row) is False

    def test_duplicate_replay_does_not_create_a_second_row(
        self, store: ClickHouseAnalyticsStore, fake_executor: FakeClickHouseExecutor
    ) -> None:
        row = make_measurement_outcome_row()
        store.append_measurement_outcome(row)
        store.append_measurement_outcome(row)
        assert len(fake_executor.tables["measurement_outcome"]) == 1

    def test_different_idempotency_key_same_tenant_is_a_new_row(
        self, store: ClickHouseAnalyticsStore, fake_executor: FakeClickHouseExecutor
    ) -> None:
        store.append_measurement_outcome(
            make_measurement_outcome_row(id="mo-1", idempotency_key="idem-1")
        )
        store.append_measurement_outcome(
            make_measurement_outcome_row(id="mo-2", idempotency_key="idem-2")
        )
        assert len(fake_executor.tables["measurement_outcome"]) == 2

    def test_same_idempotency_key_different_tenant_is_not_a_duplicate(
        self, store: ClickHouseAnalyticsStore, fake_executor: FakeClickHouseExecutor
    ) -> None:
        store.append_measurement_outcome(
            make_measurement_outcome_row(tenant_id=TENANT_A, idempotency_key="idem-shared")
        )
        store.append_measurement_outcome(
            make_measurement_outcome_row(tenant_id=TENANT_B, idempotency_key="idem-shared")
        )
        assert len(fake_executor.tables["measurement_outcome"]) == 2


class TestQueryTenantInjection:
    def test_get_measurement_outcomes_returns_only_requested_tenants_rows(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        store.append_measurement_outcome(
            make_measurement_outcome_row(tenant_id=TENANT_A, id="mo-a")
        )
        store.append_measurement_outcome(
            make_measurement_outcome_row(tenant_id=TENANT_B, id="mo-b")
        )
        results = store.get_measurement_outcomes(TENANT_A)
        assert {row.id for row in results} == {"mo-a"}

    def test_cross_tenant_query_is_not_expressible(self, store: ClickHouseAnalyticsStore) -> None:
        store.append_measurement_outcome(
            make_measurement_outcome_row(tenant_id=TENANT_A, id="mo-a")
        )
        assert store.get_measurement_outcomes(TENANT_B) == ()

    def test_time_range_filters(self, store: ClickHouseAnalyticsStore) -> None:
        store.append_measurement_outcome(
            make_measurement_outcome_row(
                id="mo-jan",
                idempotency_key="idem-jan",
                occurred_at=dt.datetime(2026, 1, 15, tzinfo=dt.UTC),
            )
        )
        store.append_measurement_outcome(
            make_measurement_outcome_row(
                id="mo-feb",
                idempotency_key="idem-feb",
                occurred_at=dt.datetime(2026, 2, 15, tzinfo=dt.UTC),
            )
        )
        results = store.get_measurement_outcomes(
            TENANT_A,
            start=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
            end=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
        )
        assert {row.id for row in results} == {"mo-feb"}

    def test_limit(self, store: ClickHouseAnalyticsStore) -> None:
        for i in range(3):
            store.append_measurement_outcome(
                make_measurement_outcome_row(id=f"mo-{i}", idempotency_key=f"idem-{i}")
            )
        results = store.get_measurement_outcomes(TENANT_A, limit=2)
        assert len(results) == 2


class TestRoundTrip:
    def test_appended_row_round_trips_through_get(self, store: ClickHouseAnalyticsStore) -> None:
        row = make_measurement_outcome_row()
        store.append_measurement_outcome(row)
        (fetched,) = store.get_measurement_outcomes(TENANT_A)
        assert fetched.tenant_id == row.tenant_id
        assert fetched.id == row.id
        assert fetched.idempotency_key == row.idempotency_key
        assert fetched.experiment_id == row.experiment_id
        assert fetched.registration_canonical_hash == row.registration_canonical_hash
        assert fetched.window_started_at == row.window_started_at
        assert fetched.window_ended_at == row.window_ended_at
        assert fetched.b_verdict == row.b_verdict
        assert fetched.reason_codes == row.reason_codes
        assert fetched.outcome_layer == row.outcome_layer
        assert fetched.evidence_basis_id == row.evidence_basis_id
        assert fetched.sample_count_treatment == row.sample_count_treatment
        assert fetched.sample_count_control == row.sample_count_control
        assert fetched.insufficient_data == row.insufficient_data
        assert fetched.net_of_control_lift == row.net_of_control_lift
        assert fetched.raw_lift == row.raw_lift
        assert fetched.evidence_bundle_manifest_hash == row.evidence_bundle_manifest_hash
        assert fetched.grs_policy_version == row.grs_policy_version
        assert fetched.grs_policy_hash == row.grs_policy_hash
        assert fetched.grs_policy_provenance == row.grs_policy_provenance

    def test_null_evidence_basis_id_round_trips_as_none(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = make_measurement_outcome_row(evidence_basis_id=None)
        store.append_measurement_outcome(row)
        (fetched,) = store.get_measurement_outcomes(TENANT_A)
        assert fetched.evidence_basis_id is None

    def test_null_lift_fields_round_trip_as_none(self, store: ClickHouseAnalyticsStore) -> None:
        row = make_measurement_outcome_row(
            net_of_control_lift=None,
            raw_lift=None,
            insufficient_data=True,
            b_verdict="undetermined",
        )
        store.append_measurement_outcome(row)
        (fetched,) = store.get_measurement_outcomes(TENANT_A)
        assert fetched.net_of_control_lift is None
        assert fetched.raw_lift is None


class TestRawVsAdjustedView:
    def test_returns_both_raw_and_adjusted_lift(self, store: ClickHouseAnalyticsStore) -> None:
        store.append_measurement_outcome(
            make_measurement_outcome_row(net_of_control_lift=0.12, raw_lift=0.20)
        )
        (view_row,) = store.get_measurement_outcome_raw_vs_adjusted_view(TENANT_A)
        assert view_row.raw_lift == 0.20
        assert view_row.net_of_control_lift == 0.12

    def test_scoped_to_tenant(self, store: ClickHouseAnalyticsStore) -> None:
        store.append_measurement_outcome(
            make_measurement_outcome_row(tenant_id=TENANT_A, id="mo-a")
        )
        store.append_measurement_outcome(
            make_measurement_outcome_row(tenant_id=TENANT_B, id="mo-b")
        )
        results = store.get_measurement_outcome_raw_vs_adjusted_view(TENANT_A)
        assert {r.experiment_id for r in results} == {"exp-1"}
        assert all(r.tenant_id == TENANT_A for r in results)

    def test_filters_by_experiment_id(self, store: ClickHouseAnalyticsStore) -> None:
        store.append_measurement_outcome(
            make_measurement_outcome_row(id="mo-a", idempotency_key="idem-a", experiment_id="exp-a")
        )
        store.append_measurement_outcome(
            make_measurement_outcome_row(id="mo-b", idempotency_key="idem-b", experiment_id="exp-b")
        )
        results = store.get_measurement_outcome_raw_vs_adjusted_view(
            TENANT_A, experiment_id="exp-a"
        )
        assert {r.experiment_id for r in results} == {"exp-a"}

    def test_undetermined_row_may_have_null_lifts_in_view(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        store.append_measurement_outcome(
            make_measurement_outcome_row(
                net_of_control_lift=None,
                raw_lift=None,
                insufficient_data=True,
                b_verdict="undetermined",
            )
        )
        (view_row,) = store.get_measurement_outcome_raw_vs_adjusted_view(TENANT_A)
        assert view_row.raw_lift is None
        assert view_row.net_of_control_lift is None
        assert view_row.b_verdict == "undetermined"

    def test_duplicate_replay_collapses_to_one_view_row(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = make_measurement_outcome_row()
        store.append_measurement_outcome(row)
        store.append_measurement_outcome(row)
        results = store.get_measurement_outcome_raw_vs_adjusted_view(TENANT_A)
        assert len(results) == 1

    def test_limit_bounds_the_view(self, store: ClickHouseAnalyticsStore) -> None:
        for i in range(3):
            store.append_measurement_outcome(
                make_measurement_outcome_row(id=f"mo-{i}", idempotency_key=f"idem-{i}")
            )
        results = store.get_measurement_outcome_raw_vs_adjusted_view(TENANT_A, limit=2)
        assert len(results) == 2


class TestDeterminism:
    def test_reading_the_same_state_twice_yields_identical_results(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        for i in range(5):
            store.append_measurement_outcome(
                make_measurement_outcome_row(id=f"mo-{i}", idempotency_key=f"idem-{i}")
            )
        first = store.get_measurement_outcomes(TENANT_A)
        second = store.get_measurement_outcomes(TENANT_A)
        assert first == second

    def test_view_read_is_deterministic_across_repeated_calls(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        for i in range(3):
            store.append_measurement_outcome(
                make_measurement_outcome_row(id=f"mo-{i}", idempotency_key=f"idem-{i}")
            )
        first = store.get_measurement_outcome_raw_vs_adjusted_view(TENANT_A)
        second = store.get_measurement_outcome_raw_vs_adjusted_view(TENANT_A)
        assert first == second

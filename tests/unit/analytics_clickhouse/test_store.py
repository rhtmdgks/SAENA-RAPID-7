"""Unit tests for `saena_analytics_clickhouse.store.ClickHouseAnalyticsStore`
(w4-06 mission deliverables 2 + 6) — in-memory `FakeClickHouseExecutor` seam,
no I/O."""

from __future__ import annotations

import datetime as dt
import inspect

from analytics_clickhouse_factories import (
    TENANT_A,
    TENANT_B,
    FakeClickHouseExecutor,
    make_citation_row,
    make_experiment_registration_row,
    make_observation_row,
)
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore


class TestAppendIdempotency:
    def test_append_observation_returns_true_on_first_insert(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        assert store.append_observation(make_observation_row()) is True

    def test_append_observation_returns_false_on_duplicate_idempotency_key(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = make_observation_row()
        assert store.append_observation(row) is True
        assert store.append_observation(row) is False

    def test_duplicate_replay_does_not_create_a_second_row(
        self, store: ClickHouseAnalyticsStore, fake_executor: FakeClickHouseExecutor
    ) -> None:
        row = make_observation_row()
        store.append_observation(row)
        store.append_observation(row)
        assert len(fake_executor.tables["observations"]) == 1

    def test_different_idempotency_key_same_tenant_is_a_new_row(
        self, store: ClickHouseAnalyticsStore, fake_executor: FakeClickHouseExecutor
    ) -> None:
        store.append_observation(make_observation_row(id="obs-1", idempotency_key="idem-1"))
        store.append_observation(make_observation_row(id="obs-2", idempotency_key="idem-2"))
        assert len(fake_executor.tables["observations"]) == 2

    def test_same_idempotency_key_different_tenant_is_not_a_duplicate(
        self, store: ClickHouseAnalyticsStore, fake_executor: FakeClickHouseExecutor
    ) -> None:
        """Dedup key is `(tenant_id, idempotency_key)`, never
        `idempotency_key` alone."""
        store.append_observation(
            make_observation_row(tenant_id=TENANT_A, idempotency_key="idem-shared")
        )
        store.append_observation(
            make_observation_row(tenant_id=TENANT_B, idempotency_key="idem-shared")
        )
        assert len(fake_executor.tables["observations"]) == 2

    def test_append_citation_is_idempotent(self, store: ClickHouseAnalyticsStore) -> None:
        row = make_citation_row()
        assert store.append_citation(row) is True
        assert store.append_citation(row) is False

    def test_append_experiment_registration_is_idempotent(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = make_experiment_registration_row()
        assert store.append_experiment_registration(row) is True
        assert store.append_experiment_registration(row) is False


class TestLateOutOfOrderTolerance:
    def test_out_of_order_occurred_at_is_accepted_not_rejected(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        later = make_observation_row(
            id="obs-late",
            idempotency_key="idem-late",
            occurred_at=dt.datetime(2026, 7, 5, tzinfo=dt.UTC),
        )
        earlier = make_observation_row(
            id="obs-early",
            idempotency_key="idem-early",
            occurred_at=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        )
        assert store.append_observation(later) is True
        # A strictly-earlier event arriving AFTER a later one is tolerated —
        # no monotonicity constraint on occurred_at, only idempotency_key
        # uniqueness (module docstring).
        assert store.append_observation(earlier) is True


class TestQueryTenantInjection:
    def test_get_observations_requires_tenant_id_as_first_positional_argument(self) -> None:
        sig = inspect.signature(ClickHouseAnalyticsStore.get_observations)
        params = list(sig.parameters.values())
        assert params[1].name == "tenant_id"
        assert params[1].default is inspect.Parameter.empty

    def test_get_observations_returns_only_requested_tenants_rows(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        store.append_observation(make_observation_row(tenant_id=TENANT_A, id="obs-a"))
        store.append_observation(make_observation_row(tenant_id=TENANT_B, id="obs-b"))
        results = store.get_observations(TENANT_A)
        assert {row.id for row in results} == {"obs-a"}

    def test_cross_tenant_query_is_not_expressible(self, store: ClickHouseAnalyticsStore) -> None:
        """There is no argument/flag on `get_observations` that returns
        another tenant's rows — passing TENANT_B's id returns only
        TENANT_B's own rows, never TENANT_A's."""
        store.append_observation(make_observation_row(tenant_id=TENANT_A, id="obs-a"))
        assert store.get_observations(TENANT_B) == ()

    def test_get_citations_scoped_to_tenant(self, store: ClickHouseAnalyticsStore) -> None:
        store.append_citation(make_citation_row(tenant_id=TENANT_A, id="cit-a"))
        store.append_citation(make_citation_row(tenant_id=TENANT_B, id="cit-b"))
        results = store.get_citations(TENANT_A)
        assert {row.id for row in results} == {"cit-a"}

    def test_get_experiment_registrations_scoped_to_tenant(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        store.append_experiment_registration(
            make_experiment_registration_row(tenant_id=TENANT_A, id="exp-a")
        )
        store.append_experiment_registration(
            make_experiment_registration_row(tenant_id=TENANT_B, id="exp-b")
        )
        results = store.get_experiment_registrations(TENANT_A)
        assert {row.id for row in results} == {"exp-a"}

    def test_get_observations_time_range_filters(self, store: ClickHouseAnalyticsStore) -> None:
        store.append_observation(
            make_observation_row(
                id="obs-jan",
                idempotency_key="idem-jan",
                occurred_at=dt.datetime(2026, 1, 15, tzinfo=dt.UTC),
            )
        )
        store.append_observation(
            make_observation_row(
                id="obs-feb",
                idempotency_key="idem-feb",
                occurred_at=dt.datetime(2026, 2, 15, tzinfo=dt.UTC),
            )
        )
        results = store.get_observations(
            TENANT_A,
            start=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
            end=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
        )
        assert {row.id for row in results} == {"obs-feb"}

    def test_get_observations_limit(self, store: ClickHouseAnalyticsStore) -> None:
        for i in range(3):
            store.append_observation(
                make_observation_row(id=f"obs-{i}", idempotency_key=f"idem-{i}")
            )
        results = store.get_observations(TENANT_A, limit=2)
        assert len(results) == 2


class TestRoundTrip:
    def test_appended_observation_round_trips_through_get(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = make_observation_row()
        store.append_observation(row)
        (fetched,) = store.get_observations(TENANT_A)
        assert fetched.tenant_id == row.tenant_id
        assert fetched.id == row.id
        assert fetched.idempotency_key == row.idempotency_key
        assert fetched.engine_id == row.engine_id
        assert fetched.run_id == row.run_id
        assert fetched.query_ref == row.query_ref
        assert fetched.query_digest == row.query_digest
        assert fetched.citation_refs == row.citation_refs
        assert fetched.raw_object_ref == row.raw_object_ref

    def test_appended_citation_round_trips_through_get(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = make_citation_row()
        store.append_citation(row)
        (fetched,) = store.get_citations(TENANT_A)
        assert fetched.contribution_score == row.contribution_score
        assert fetched.source_domain == row.source_domain

    def test_appended_experiment_registration_round_trips_through_get(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = make_experiment_registration_row()
        store.append_experiment_registration(row)
        (fetched,) = store.get_experiment_registrations(TENANT_A)
        assert fetched.status == row.status
        assert fetched.registration_hash == row.registration_hash

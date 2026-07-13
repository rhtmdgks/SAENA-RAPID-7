"""Integration tests — `ClickHouseAnalyticsStore` against a REAL ClickHouse
container (testcontainers, `clickhouse/clickhouse-server` image; w4-06
mission deliverable 5: "append, dedup replay, out-of-order, cross-tenant
isolation").

Docker unavailable / `clickhouse-connect` not installed -> every test in
this module is skipped with an honest, distinct reason
(`conftest.py::pytest_collection_modifyitems`), never silently passed.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from saena_analytics_clickhouse.query_privacy import QuerySigningKeyRef, derive_query_ref
from saena_analytics_clickhouse.rows import CitationRow, ExperimentRegistrationRow, ObservationRow
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore

pytestmark = pytest.mark.integration

TENANT_A = "acme-co"
TENANT_B = "globex-co"

# `derive_query_ref` (independent-critic MUST-FIX round 2) is now KEYED and
# fail-closed. `_TEST_SIGNING_KEY_REF` is deliberately DUPLICATED (not
# `from conftest import ...`) in every test module of this directory that
# needs one — a plain `import conftest`/`from conftest import` is
# collision-prone once the whole `tests/` suite is collected together under
# pytest's default `prepend` import mode (see `tests/integration/vector/
# test_pgvector_store.py`'s own identical `TEST_DIMENSION` precedent/
# rationale, and `conftest.py`'s own `TEST_QUERY_SIGNING_KEY_ENV_VAR` — kept
# in sync by hand, same env var NAME both places, a mismatch would surface
# immediately as a `MissingQuerySigningKeyError` in every test, never a
# silent pass).
_TEST_SIGNING_KEY_ENV_VAR = "SAENA_ANALYTICS_QUERY_SIGNING_KEY__INTEGRATION_TEST_FIXTURE"
_TEST_SIGNING_KEY_REF = QuerySigningKeyRef(env_var=_TEST_SIGNING_KEY_ENV_VAR)


def _observation(**overrides: Any) -> ObservationRow:
    tenant_id = overrides.get("tenant_id", TENANT_A)
    fields: dict[str, Any] = {
        "tenant_id": tenant_id,
        "id": "obs-1",
        "idempotency_key": "idem-1",
        "occurred_at": dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        "engine_id": "chatgpt-search",
        "run_id": "run-1",
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
        "id": "cit-1",
        "idempotency_key": "idem-cit-1",
        "occurred_at": dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        "run_id": "run-1",
        "observation_id": "obs-1",
        "citation_ref": "ref://citation/1",
        "source_domain": "example.com",
        "contribution_score": 0.5,
    }
    fields.update(overrides)
    return CitationRow(**fields)


def _experiment_registration(**overrides: Any) -> ExperimentRegistrationRow:
    fields: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "id": "exp-1",
        "idempotency_key": "idem-exp-1",
        "occurred_at": dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        "engine_id": "chatgpt-search",
        "locale": "en-US",
        "observation_cell": "cell-1",
        "registration_hash": "sha256:abc123",
        "status": "registered",
    }
    fields.update(overrides)
    return ExperimentRegistrationRow(**fields)


class TestAppendRoundTrip:
    def test_observation_append_then_get_round_trips(self, store: ClickHouseAnalyticsStore) -> None:
        row = _observation()
        assert store.append_observation(row) is True
        (fetched,) = store.get_observations(TENANT_A)
        assert fetched.id == row.id
        assert fetched.query_ref == row.query_ref
        assert fetched.query_digest == row.query_digest
        assert fetched.citation_refs == row.citation_refs

    def test_citation_append_then_get_round_trips(self, store: ClickHouseAnalyticsStore) -> None:
        row = _citation()
        assert store.append_citation(row) is True
        (fetched,) = store.get_citations(TENANT_A)
        assert fetched.contribution_score == row.contribution_score

    def test_experiment_registration_append_then_get_round_trips(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = _experiment_registration()
        assert store.append_experiment_registration(row) is True
        (fetched,) = store.get_experiment_registrations(TENANT_A)
        assert fetched.status == row.status


class TestDedupReplay:
    def test_duplicate_idempotency_key_replay_is_a_no_op(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = _observation()
        assert store.append_observation(row) is True
        assert store.append_observation(row) is False
        assert len(store.get_observations(TENANT_A)) == 1

    def test_duplicate_replay_across_multiple_attempts_stays_single_row(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        row = _observation()
        for _ in range(3):
            store.append_observation(row)
        assert len(store.get_observations(TENANT_A)) == 1


class TestOutOfOrderTolerance:
    def test_late_arriving_earlier_event_is_accepted_not_rejected(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        later = _observation(
            id="obs-late",
            idempotency_key="idem-late",
            occurred_at=dt.datetime(2026, 7, 5, tzinfo=dt.UTC),
        )
        earlier = _observation(
            id="obs-early",
            idempotency_key="idem-early",
            occurred_at=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        )
        assert store.append_observation(later) is True
        assert store.append_observation(earlier) is True
        results = store.get_observations(TENANT_A)
        assert {row.id for row in results} == {"obs-late", "obs-early"}


class TestCrossTenantIsolation:
    def test_get_observations_never_returns_another_tenants_rows(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        store.append_observation(_observation(tenant_id=TENANT_A, id="obs-a"))
        store.append_observation(
            _observation(tenant_id=TENANT_B, id="obs-b", idempotency_key="idem-b")
        )
        assert {row.id for row in store.get_observations(TENANT_A)} == {"obs-a"}
        assert {row.id for row in store.get_observations(TENANT_B)} == {"obs-b"}

    def test_same_idempotency_key_different_tenants_both_land(
        self, store: ClickHouseAnalyticsStore
    ) -> None:
        store.append_observation(
            _observation(tenant_id=TENANT_A, id="obs-shared-a", idempotency_key="idem-shared")
        )
        store.append_observation(
            _observation(tenant_id=TENANT_B, id="obs-shared-b", idempotency_key="idem-shared")
        )
        assert len(store.get_observations(TENANT_A)) == 1
        assert len(store.get_observations(TENANT_B)) == 1

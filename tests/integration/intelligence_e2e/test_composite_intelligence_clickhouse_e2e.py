"""Wave 4 composite synthetic E2E (w4-17) — ClickHouse-backed companion.

Runs the SAME whole intelligence chain `tests/e2e/intelligence/
test_composite_intelligence_e2e.py` proves (demand-graph -> chatgpt-observer
-> citation-intelligence -> entity-resolution -> vector-store -> claim-
evidence -> QEEG -> experiment ledger), reusing that package's own
`intelligence_e2e_harness` module so both lanes build from byte-identical
synthetic input, and additionally persists each observation into a REAL
`saena_analytics_clickhouse.ClickHouseAnalyticsStore` backed by a real
`clickhouse/clickhouse-server` testcontainer (ADR-0017) — proving the
`observation.captured.v1` -> ClickHouse `observations` table leg of the
mission's own "observations stored (artifact gateway + optionally
ClickHouse if a container is used)" instruction.

Docker unavailable -> every test in this module is skipped with an honest,
distinct reason (`conftest.py::pytest_collection_modifyitems`), never
silently passed.
"""

from __future__ import annotations

import datetime as dt
import os

import pytest
from intelligence_e2e_harness import ENGINE_ID, RUN_ID, TENANT_1, TENANT_2, run_composite_chain
from saena_analytics_clickhouse.query_privacy import QuerySigningKeyRef, derive_query_ref
from saena_analytics_clickhouse.rows import ObservationRow
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore

pytestmark = pytest.mark.integration

# `derive_query_ref` (independent-critic MUST-FIX round 2) is now KEYED and
# fail-closed, exactly like `derive_query_digest` — this module needs a
# deterministic test signing key to project `ObservationRow`s. A DEDICATED
# env var name, set once at module-import time to a fixed, obviously-
# synthetic value — never a real secret. `os.environ.setdefault` so a real
# run that already set this var for its own reason is never silently
# overwritten.
_TEST_QUERY_SIGNING_KEY_ENV_VAR = "SAENA_ANALYTICS_QUERY_SIGNING_KEY__E2E_TEST_FIXTURE"
os.environ.setdefault(
    _TEST_QUERY_SIGNING_KEY_ENV_VAR, "e2e-test-fixture-signing-key-not-a-real-secret"
)
_TEST_SIGNING_KEY_REF = QuerySigningKeyRef(env_var=_TEST_QUERY_SIGNING_KEY_ENV_VAR)


def _observation_row_from_pooled_result(pooled_result, *, tenant_id: str) -> ObservationRow:
    """Project one `PooledObservationResult`'s formal `PlatformObservation`
    record into this package's own `ObservationRow` shape (`rows.py` module
    docstring: "ObservationRow's field set deliberately mirrors
    PlatformObservation ... reusing the same field names/shapes keeps a
    future ChatgptObserverService -> analytics-clickhouse writer a straight
    field copy, not a translation layer") — exactly that straight field
    copy, performed here as this E2E's own writer glue (this package is a
    standalone leaf per its own module docstring; it never imports
    `saena_chatgpt_observer` itself). r4-04 (round 2: KEYED, fail-closed):
    `query_ref` REPLACES the pre-fix `query_text` field —
    `record["observation_id"]` is not itself a real query (the formal
    record does not carry one, see the ORIGINAL comment this replaces), it
    is this harness's own deterministic stand-in, now passed through
    `derive_query_ref` like a real caller's raw query would be, rather than
    assigned directly to a raw-text field that no longer exists on this row
    type."""
    record = pooled_result.observation_record
    return ObservationRow(
        tenant_id=tenant_id,
        id=record["observation_id"],
        idempotency_key=f"{tenant_id}:{RUN_ID}:{record['observation_id']}",
        occurred_at=dt.datetime.fromisoformat(record["captured_at"].replace("Z", "+00:00")),
        engine_id=record["engine_id"],
        run_id=record["run_id"],
        query_ref=derive_query_ref(
            tenant_id=tenant_id,
            raw_query=record["observation_id"],
            signing_key_ref=_TEST_SIGNING_KEY_REF,
        ).query_ref,
        citation_refs=tuple(record["citation_refs"]),
        raw_object_ref=record["raw_object_ref"],
    )


class TestObservationsPersistToRealClickHouse:
    def test_every_observation_round_trips_through_a_real_clickhouse_table(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        chain_result = run_composite_chain(tenant_id=TENANT_1)

        for pooled_result in chain_result.observation_run.results:
            row = _observation_row_from_pooled_result(pooled_result, tenant_id=TENANT_1)
            inserted = analytics_store.append_observation(row)
            assert inserted is True

        fetched = analytics_store.get_observations(TENANT_1)
        assert len(fetched) == len(chain_result.observation_run.results)
        fetched_by_id = {row.id: row for row in fetched}
        for pooled_result in chain_result.observation_run.results:
            observation_id = pooled_result.observation_record["observation_id"]
            assert fetched_by_id[observation_id].engine_id == ENGINE_ID
            assert (
                fetched_by_id[observation_id].raw_object_ref
                == (pooled_result.observation_record["raw_object_ref"])
            )
            assert fetched_by_id[observation_id].citation_refs == tuple(
                pooled_result.observation_record["citation_refs"]
            )

    def test_duplicate_idempotency_key_replay_against_real_clickhouse_is_a_no_op(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        chain_result = run_composite_chain(tenant_id=TENANT_1)
        row = _observation_row_from_pooled_result(
            chain_result.observation_run.results[0], tenant_id=TENANT_1
        )
        assert analytics_store.append_observation(row) is True
        assert analytics_store.append_observation(row) is False
        assert len(analytics_store.get_observations(TENANT_1)) == 1

    def test_cross_tenant_observations_never_leak_in_a_real_clickhouse_query(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        run_1 = run_composite_chain(tenant_id=TENANT_1)
        run_2 = run_composite_chain(tenant_id=TENANT_2)

        row_1 = _observation_row_from_pooled_result(
            run_1.observation_run.results[0], tenant_id=TENANT_1
        )
        row_2 = _observation_row_from_pooled_result(
            run_2.observation_run.results[0], tenant_id=TENANT_2
        )
        analytics_store.append_observation(row_1)
        analytics_store.append_observation(row_2)

        tenant_1_rows = analytics_store.get_observations(TENANT_1)
        tenant_2_rows = analytics_store.get_observations(TENANT_2)
        assert {r.id for r in tenant_1_rows} == {row_1.id}
        assert {r.id for r in tenant_2_rows} == {row_2.id}


class TestDeterminismSurvivesTheRealClickHouseRoundTrip:
    def test_artifact_hash_is_byte_identical_before_and_after_the_round_trip(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        """The SAME deterministic hash the pure-synthetic lane proves
        (`tests/e2e/intelligence/test_composite_intelligence_e2e.py::
        TestDeterminism`) survives a REAL ClickHouse insert + query round
        trip unchanged — `raw_object_ref`/`artifact_hash` are opaque string
        columns, never recomputed or reshaped by the store."""
        chain_result = run_composite_chain(tenant_id=TENANT_1)
        pooled_result = chain_result.observation_run.results[0]
        row = _observation_row_from_pooled_result(pooled_result, tenant_id=TENANT_1)
        analytics_store.append_observation(row)

        (fetched,) = analytics_store.get_observations(TENANT_1)
        assert fetched.raw_object_ref == pooled_result.observation_record["raw_object_ref"]
        assert fetched.raw_object_ref == pooled_result.raw_object_ref

    def test_whole_chain_replayed_twice_yields_the_same_row_content_both_times(
        self, analytics_store: ClickHouseAnalyticsStore
    ) -> None:
        run_a = run_composite_chain(tenant_id=TENANT_1)
        run_b = run_composite_chain(tenant_id=TENANT_1)

        row_a = _observation_row_from_pooled_result(
            run_a.observation_run.results[0], tenant_id=TENANT_1
        )
        assert (
            row_a.raw_object_ref
            == _observation_row_from_pooled_result(
                run_b.observation_run.results[0], tenant_id=TENANT_1
            ).raw_object_ref
        )

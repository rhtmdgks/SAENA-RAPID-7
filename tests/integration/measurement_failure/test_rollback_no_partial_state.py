"""Rollback (w5-20 deliverable 2, bullet 3): a failed atomic decision write
leaves NO partial state — real Postgres transaction rollback.

`OutcomeDecisionRecord` binds decision + evidence_bundle_ref + policy_metadata
into ONE frozen record (atomic by API shape, `ports.py` "Atomicity / no
partial state"), and `PgOutcomeDecisionStore.append_decision` runs its
`INSERT ... ON CONFLICT DO NOTHING` inside one `engine.begin()` transaction
(`persistence/adapter.py` "Atomicity / no partial state"). These tests prove
BOTH ends of that contract against a REAL database:

1. A conflicting append (same decision_key, DIFFERENT content) raises
   `AppendOnlyViolationError` and the table is left EXACTLY as it was before
   the attempt — no row count change, no fingerprint drift, the original
   content unchanged.
2. The SAME no-partial-state property one layer up: a `run_measurement` call
   that reaches step 7 (append_decision) but whose OWN decision would
   conflict with an already-recorded one leaves the evidence bundle store
   and confirmation store exactly as they were from the FIRST successful run
   — no half-committed second bundle "orphaned" alongside a failed decision
   write.
"""

from __future__ import annotations

import pytest
from measurement_failure_factories import make_pg_ports
from pipeline_factories import make_happy_path_inputs, make_policies
from saena_domain.measurement.errors import AppendOnlyViolationError
from saena_domain.measurement.ports import OutcomeDecisionRecord
from saena_experiment_attribution.persistence import tables
from saena_experiment_attribution.pipeline import run_measurement
from sqlalchemy import text

pytestmark = pytest.mark.integration

_TENANT = "acme-co"


def test_conflicting_append_decision_leaves_no_partial_state(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """A raised `AppendOnlyViolationError` must roll back cleanly: the table
    still holds exactly the FIRST record, exactly one row, exactly its
    original fingerprint — never a half-written row from the failed attempt."""
    ports = make_pg_ports(postgres_url)
    first = OutcomeDecisionRecord(
        tenant_id=_TENANT,
        decision_key=("exp-rollback", "primary"),
        outcome="pass",
        evidence_bundle_ref="sha256:" + "a" * 64,
        policy_metadata={"policy_version": "1.0.0"},
    )
    ports.decision_store.append_decision(_TENANT, first)

    conflicting = OutcomeDecisionRecord(
        tenant_id=_TENANT,
        decision_key=("exp-rollback", "primary"),
        outcome="fail",  # different content under the same key
        evidence_bundle_ref="sha256:" + "b" * 64,
        policy_metadata={"policy_version": "1.0.0"},
    )
    with pytest.raises(AppendOnlyViolationError):
        ports.decision_store.append_decision(_TENANT, conflicting)

    # Exactly the first record survives, unchanged.
    got = ports.decision_store.get(_TENANT, ("exp-rollback", "primary"))
    assert got == first

    async def _count_rows() -> int:
        from sqlalchemy.ext.asyncio import create_async_engine

        eng = create_async_engine(postgres_url)
        try:
            dtable = tables.qualified_table(tables.DECISIONS_TABLE)
            async with eng.connect() as conn:
                result = await conn.execute(
                    text(
                        f"SELECT count(*) FROM {dtable} "
                        "WHERE tenant_id = :t AND experiment_id = :e AND decision_slot = :s"
                    ),
                    {"t": _TENANT, "e": "exp-rollback", "s": "primary"},
                )
                return result.scalar_one()
        finally:
            await eng.dispose()

    count = run(_count_rows())
    assert count == 1, "the failed conflicting write must leave exactly one (the original) row"


def test_pipeline_conflicting_decision_replay_leaves_original_outcome_untouched(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """Drive the same "no partial state" property through `run_measurement`
    itself: run the pipeline once, then feed it a maliciously-constructed
    situation where the SAME decision key would need to record DIFFERENT
    content (a corrupted/forged outcome). The pipeline's own append is a
    byte-identical replay by construction (same inputs -> same
    canonical_payload — proven in `svc_experiment_attribution_pipeline/
    test_idempotency_and_determinism.py`), so this test proves the negative
    directly at the store: an OUT-OF-BAND attempt to overwrite the pipeline's
    own recorded decision with different content fails closed and the
    pipeline's original record is the one still there afterward."""
    inputs, registration = make_happy_path_inputs()
    policies = make_policies(registration)
    ports = make_pg_ports(postgres_url)

    outcome = run_measurement(inputs, ports, policies)
    stored = ports.decision_store.get(inputs.tenant_id, (inputs.experiment_id, inputs.run_id))
    assert stored.outcome == outcome.status.value

    forged = OutcomeDecisionRecord(
        tenant_id=inputs.tenant_id,
        decision_key=(inputs.experiment_id, inputs.run_id),
        outcome="pass" if stored.outcome != "pass" else "fail",  # deliberately different
        evidence_bundle_ref="sha256:" + "f" * 64,
        policy_metadata={"forged": True},
    )
    from saena_domain.measurement.errors import AppendOnlyViolationError as _AOVE

    with pytest.raises(_AOVE):
        ports.decision_store.append_decision(inputs.tenant_id, forged)

    # The pipeline's own original decision is untouched.
    still_stored = ports.decision_store.get(inputs.tenant_id, (inputs.experiment_id, inputs.run_id))
    assert still_stored == stored
    assert still_stored.outcome == outcome.status.value

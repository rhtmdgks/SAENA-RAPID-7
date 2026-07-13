"""At-least-once replay (w5-20 deliverable 2, bullet 2): duplicate
`deployment.confirmed` + duplicate observations -> a single outcome,
idempotent across store + validation + workflow levels.

Three levels, matching the mission's explicit "across store + validation +
workflow levels" phrasing:

1. STORE level: the real Postgres `ConfirmationStore`/`OutcomeDecisionStore`
   already prove single-row idempotency in `measurement_pg/
   test_measurement_pg_semantics.py` (w5-10) — this module does not repeat
   that; instead it drives the SAME at-least-once redelivery through the
   PIPELINE entry point (`run_measurement`) so the store-level guarantee is
   proven end-to-end, not just at the bare port.
2. VALIDATION level: `saena_domain.measurement.confirmation.
   validate_confirmation` (w5-03) returns `Duplicate` (not a fresh `Accepted`)
   for a byte-identical redelivered confirmation — proven directly against
   the real validator, independent of any store.
3. WORKFLOW level: `MeasurementWorkflow`'s duplicate-signal idempotency
   (timer NOT restarted) is already exhaustively covered by w5-14's own
   REAL Temporal time-skipping suite
   (`tests/integration/measurement_workflow/
   test_measurement_workflow.py::test_duplicate_deployment_signal_is_idempotent_no_restart`)
   — cross-referenced here rather than duplicated (this suite adds no
   second, weaker copy of a Temporal harness); this module's own workflow-
   level check is `test_conflicting_replay.py`'s workflow-level conflicting
   confirmation test, which shares the same signal-delivery path.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from measurement_failure_factories import make_pg_ports
from pipeline_factories import (
    AlwaysTrustVerifier,
    make_happy_path_inputs,
    make_policies,
    make_registration_view,
)
from saena_domain.measurement.confirmation import Accepted, Duplicate, validate_confirmation
from saena_domain.measurement.ports import PutOutcome
from saena_experiment_attribution.pipeline import run_measurement

pytestmark = __import__("pytest").mark.integration


# --- 1. Pipeline-level: duplicate deployment.confirmed -> single outcome ---


def test_duplicate_pipeline_runs_over_real_postgres_yield_single_outcome(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """The SAME `MeasurementInputs` (same `deployment_confirmation`, same
    `observations`, same idempotency keys) run through `run_measurement`
    THREE times — simulating at-least-once delivery of the same
    `deployment.confirmed.v1` event plus its observation batch — must yield
    exactly ONE stored decision and ONE stored confirmation row, and every
    run's outcome record is byte-identical."""
    inputs, registration = make_happy_path_inputs()
    policies = make_policies(registration)
    ports = make_pg_ports(postgres_url)

    outcomes = [run_measurement(inputs, ports, policies) for _ in range(3)]

    payloads = [o.canonical_payload() for o in outcomes]
    assert payloads[0] == payloads[1] == payloads[2]

    decisions = ports.decision_store.list_decisions(inputs.tenant_id)
    assert len(decisions) == 1

    # The confirmation itself was stored exactly once (STORED), the
    # replays resolved DUPLICATE — proven by re-issuing the identical write
    # directly and checking its outcome.
    replay_result = ports.confirmation_store.put_confirmation(
        inputs.tenant_id,
        inputs.deployment_confirmation.idempotency_key,
        ports.confirmation_store.get(
            inputs.tenant_id, inputs.deployment_confirmation.idempotency_key
        ),
    )
    assert replay_result.outcome is PutOutcome.DUPLICATE


def test_duplicate_observations_within_a_signal_do_not_inflate_sample_counts(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """A DiD signal fed the SAME repeat observation twice (identical
    `observation_id` + identical value/timestamp — an at-least-once-delivered
    observation.captured event) must collapse to ONE counted repeat, never
    two, and the resulting outcome is identical to running with the
    single (de-duplicated) repeat. Runs the real pipeline against Postgres so
    the invariant is proven all the way through DiD -> B-gate -> outcome, not
    just at the DiD unit level.

    Uses the SAME run_id/experiment_id for both invocations — this IS the
    at-least-once replay scenario the test names (a redelivered
    observation.captured batch for the SAME run, not a second independent
    run). `did.py`'s own dedup (module docstring) collapses the duplicated
    repeat BEFORE it ever reaches the evidence bundle, so the sealed
    manifest's `entries` (and therefore `manifest_hash`, content-addressed
    over `entries` only per `evidence.py`'s position-committing chain) are
    byte-identical to the baseline run's, and the SAME decision_key means
    the second `append_decision` resolves DUPLICATE rather than a
    conflicting second write. A DIFFERENT run_id/experiment_id would
    produce the SAME `manifest_hash` (entries unaffected by run_id) but a
    DIFFERENT full manifest dict (`run_id`/`experiment_id` ARE top-level
    manifest fields folded into the evidence store's content_fingerprint) —
    the content-addressed evidence store correctly refuses that as
    `EvidenceHashMismatchError` (a real hash-collision guard, not a bug);
    this test deliberately does not exercise that different-identity path
    (see `test_conflicting_replay.py` for the same-key-different-content
    contract instead)."""
    inputs, registration = make_happy_path_inputs()
    policies = make_policies(registration)

    # Duplicate ONE repeat (identical id/value/timestamp) inside the first
    # signal's post_treatment cell — an at-least-once replay of a single
    # observation.captured event, not a second distinct observation.
    first_signal = inputs.signals[0]
    post_treatment = first_signal.post_treatment
    assert post_treatment is not None
    duplicated_post_treatment = post_treatment.model_copy(
        update={
            "repeat_values": post_treatment.repeat_values + (post_treatment.repeat_values[0],),
            "timestamps": post_treatment.timestamps + (post_treatment.timestamps[0],),
            "observation_ids": (
                (post_treatment.observation_ids or ())
                + ((post_treatment.observation_ids or ())[0],)
                if post_treatment.observation_ids
                else None
            ),
        }
    )
    duplicated_signal = first_signal.model_copy(
        update={"post_treatment": duplicated_post_treatment}
    )
    replayed_inputs = dataclasses.replace(inputs, signals=(duplicated_signal, *inputs.signals[1:]))

    outcome_baseline = run_measurement(inputs, make_pg_ports(postgres_url), policies)
    outcome_with_duplicate_repeat = run_measurement(
        replayed_inputs, make_pg_ports(postgres_url), policies
    )

    # Both outcomes qualify the SAME layers with the SAME lift — the
    # duplicate repeat contributed NO extra weight to the mean.
    assert outcome_with_duplicate_repeat.status == outcome_baseline.status
    assert outcome_with_duplicate_repeat.qualifying_layers == outcome_baseline.qualifying_layers
    # The de-duplicated repeat means the two runs' evidence bundles are
    # content-identical (dedup happens before evidence sealing) — proving the
    # duplicate observation left NO trace in the sealed evidence, not just an
    # unaffected verdict — and the decision store still holds exactly ONE
    # decision for this run (the replay resolved DUPLICATE, not a second,
    # arbitrary write).
    assert outcome_with_duplicate_repeat.evidence_bundle_ref == outcome_baseline.evidence_bundle_ref
    decisions = make_pg_ports(postgres_url).decision_store.list_decisions(inputs.tenant_id)
    assert len(decisions) == 1


# --- 2. Validation-level: duplicate deployment.confirmed -> Duplicate, not a fresh Accepted ---


def test_validate_confirmation_duplicate_delivery_returns_duplicate_not_fresh_accepted() -> None:
    """Direct proof against the real `validate_confirmation` (w5-03): the
    SAME confirmation payload presented a second time to the SAME prior-state
    map resolves to `Duplicate` wrapping the ORIGINAL `Accepted`, never a
    second independently-minted `Accepted`."""
    from pipeline_factories import make_deployment_confirmation, make_registration

    registration = make_registration()
    registration_view = make_registration_view(registration)
    confirmation = make_deployment_confirmation(registration, registration_view)
    server_received_at = confirmation.confirmed_at + timedelta(seconds=5)

    first = validate_confirmation(
        confirmation, registration_view, server_received_at, AlwaysTrustVerifier(), {}
    )
    assert isinstance(first, Accepted)

    prior_state = {confirmation.idempotency_key: first}
    second = validate_confirmation(
        confirmation,
        registration_view,
        server_received_at + timedelta(seconds=1),
        AlwaysTrustVerifier(),
        prior_state,
    )

    assert isinstance(second, Duplicate)
    assert second.accepted == first
    assert second.accepted.content_fingerprint == first.content_fingerprint

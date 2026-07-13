"""Idempotent replay (same inputs -> no duplicate decision) and determinism
(same inputs -> byte-identical outcome record, twice) — both on the happy
path AND on a representative fail-closed path."""

from __future__ import annotations

import dataclasses

from pipeline_factories import make_happy_path_inputs, make_policies, make_ports
from saena_domain.measurement.ports import PutOutcome
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement


def test_replay_is_idempotent_no_duplicate_decision() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration)

    run_measurement(inputs, ports, policies)
    run_measurement(inputs, ports, policies)
    run_measurement(inputs, ports, policies)

    decisions = ports.decision_store.list_decisions(inputs.tenant_id)
    assert len(decisions) == 1


def test_replay_produces_byte_identical_outcome_record() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration)

    first = run_measurement(inputs, ports, policies)
    second = run_measurement(inputs, ports, policies)

    assert first.canonical_payload() == second.canonical_payload()


def test_determinism_two_fresh_runs_same_inputs_byte_identical() -> None:
    """Two INDEPENDENT pipeline runs (fresh ports each time) over identical
    inputs must produce byte-identical outcome records — determinism must not
    depend on shared mutable state between calls."""
    inputs, registration = make_happy_path_inputs()
    policies = make_policies(registration)

    outcome_a = run_measurement(inputs, make_ports(), policies)
    outcome_b = run_measurement(inputs, make_ports(), policies)

    assert outcome_a.canonical_payload() == outcome_b.canonical_payload()
    assert outcome_a.evidence_bundle_ref == outcome_b.evidence_bundle_ref


def test_determinism_holds_on_fail_closed_path_too() -> None:
    inputs, registration = make_happy_path_inputs()
    bad_inputs = dataclasses.replace(inputs, registration=None)
    policies = make_policies(registration)

    outcome_a = run_measurement(bad_inputs, make_ports(), policies)
    outcome_b = run_measurement(bad_inputs, make_ports(), policies)

    assert outcome_a.status is OutcomeStatus.UNDETERMINED
    assert outcome_a.canonical_payload() == outcome_b.canonical_payload()


def test_replay_reports_duplicate_confirmation_store_write() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration)

    run_measurement(inputs, ports, policies)
    # The second run's confirmation write must resolve as a DUPLICATE
    # idempotent no-op, not a second stored record or a conflict.
    result = ports.confirmation_store.put_confirmation(
        inputs.tenant_id,
        inputs.deployment_confirmation.idempotency_key,
        ports.confirmation_store.get(
            inputs.tenant_id, inputs.deployment_confirmation.idempotency_key
        ),
    )
    assert result.outcome is PutOutcome.DUPLICATE


def test_replay_reports_duplicate_outcome_decision() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration)

    run_measurement(inputs, ports, policies)
    stored_first = ports.decision_store.get(inputs.tenant_id, (inputs.experiment_id, inputs.run_id))
    outcome_second = run_measurement(inputs, ports, policies)
    stored_second = ports.decision_store.get(
        inputs.tenant_id, (inputs.experiment_id, inputs.run_id)
    )

    assert stored_first == stored_second
    assert (
        outcome_second.canonical_payload()["evidence_bundle_ref"]
        == stored_second.evidence_bundle_ref
    )

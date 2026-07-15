"""E2/E4: deployment.confirmed.v1 is the ONLY clock start; unconfirmed / late
/ incomplete-window all UNDETERMINED with the specific reason code(s)."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from pipeline_factories import (
    AlwaysRejectVerifier,
    make_deployment_confirmation,
    make_happy_path_inputs,
    make_policies,
    make_ports,
    make_registration,
    make_registration_view,
    make_submission,
)
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement
from saena_experiment_attribution.pipeline.inputs import MeasurementInputs


def test_untrusted_confirmer_is_undetermined_deployment_unconfirmed() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration, trust_verifier=AlwaysRejectVerifier())

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.DEPLOYMENT_UNCONFIRMED in outcome.reason_codes


def test_no_verifier_at_all_is_undetermined() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration, trust_verifier=None)

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.DEPLOYMENT_UNCONFIRMED in outcome.reason_codes


def test_window_incomplete_is_undetermined() -> None:
    inputs, registration = make_happy_path_inputs()
    early_inputs = dataclasses.replace(
        inputs, evaluation_at=inputs.server_received_at + timedelta(days=1)
    )
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(early_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.WINDOW_INCOMPLETE in outcome.reason_codes


def test_deployment_late_day2_rule_is_undetermined() -> None:
    """Algorithm §7.3:483 — a deployment confirmed after Day 2 must never
    start the 7-day clock."""
    registration = make_registration()
    registration_view = make_registration_view(registration)
    submission = make_submission(registration)
    late_confirmed_at = registration_view.approved_at + timedelta(days=5)
    server_received_at = late_confirmed_at + timedelta(seconds=5)
    confirmation = make_deployment_confirmation(
        registration, registration_view, confirmed_at=late_confirmed_at
    )

    inputs = MeasurementInputs(
        tenant_id=registration.tenant_id,
        run_id=registration.run_id,
        experiment_id=registration.experiment_id,
        registration=registration,
        registration_view=registration_view,
        submission=submission,
        signals=(),
        deployment_confirmation=confirmation,
        server_received_at=server_received_at,
        evaluation_at=server_received_at + timedelta(days=8),
        prior_confirmations={},
        grs_inputs={"grs": 100, "independent_layers": 2, "open_incidents": 0},
    )
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.DEPLOYMENT_LATE in outcome.reason_codes


def test_conflicting_replay_is_undetermined() -> None:
    """A confirmation idempotency-key collision with DIFFERENT content
    already recorded in prior_confirmations must never be silently resolved
    to either window — fail-closed conflicting_replay."""
    from saena_domain.measurement.confirmation import validate_confirmation

    registration = make_registration()
    registration_view = make_registration_view(registration)
    submission = make_submission(registration)

    first_confirmation = make_deployment_confirmation(registration, registration_view)
    server_received_at = first_confirmation.confirmed_at + timedelta(seconds=5)
    from pipeline_factories import AlwaysTrustVerifier

    accepted = validate_confirmation(
        first_confirmation,
        registration_view,
        server_received_at,
        AlwaysTrustVerifier(),
        {},
    )
    prior_state = {first_confirmation.idempotency_key: accepted}

    conflicting_confirmation = make_deployment_confirmation(
        registration,
        registration_view,
        idempotency_key=first_confirmation.idempotency_key,
        confirmed_at=first_confirmation.confirmed_at + timedelta(minutes=1),
    )

    inputs = MeasurementInputs(
        tenant_id=registration.tenant_id,
        run_id=registration.run_id,
        experiment_id=registration.experiment_id,
        registration=registration,
        registration_view=registration_view,
        submission=submission,
        signals=(),
        deployment_confirmation=conflicting_confirmation,
        server_received_at=server_received_at + timedelta(minutes=1),
        evaluation_at=server_received_at + timedelta(days=8),
        prior_confirmations=prior_state,
        grs_inputs={"grs": 100, "independent_layers": 2, "open_incidents": 0},
    )
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.CONFLICTING_CONFIRMATION in outcome.reason_codes


def test_window_fail_never_passes_even_with_two_qualifying_signals() -> None:
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    ports = make_ports()
    policies = make_policies(registration, trust_verifier=AlwaysRejectVerifier())

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.status is not OutcomeStatus.PASS
    assert outcome.status is OutcomeStatus.UNDETERMINED

"""E3/E4: DiD insufficiency propagation, F-9 fraud fixture never PASSes, and
the ≥2-independent-layer B-gate boundary (1 qualifying layer != PASS)."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from pipeline_factories import (
    make_fraud_signal,
    make_happy_path_inputs,
    make_policies,
    make_ports,
)
from saena_domain.measurement.did import CellObservation
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement


def test_fraud_fixture_raw_up_control_up_never_passes() -> None:
    """k3s §10 F-9: raw citation count grows but control too -> never PASS."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    fraud_signals = tuple(
        make_fraud_signal(s.layer, s.evidence_basis_id, window_anchor=inputs.server_received_at)
        for s in inputs.signals
    )
    bad_inputs = dataclasses.replace(inputs, signals=fraud_signals)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is not OutcomeStatus.PASS
    assert outcome.status is OutcomeStatus.FAIL
    assert ReasonCode.NEGATIVE_OR_INCONCLUSIVE_LIFT in outcome.reason_codes
    # The raw view still shows the raw treatment movement (k3s §9.2:485 raw +
    # causal reporting together) even though it never qualified.
    assert set(outcome.raw_view) == {s.layer for s in inputs.signals}
    assert outcome.control_adjusted_view == ()


def test_fraud_fixture_never_promoted_by_grs_eligibility() -> None:
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    fraud_signals = tuple(
        make_fraud_signal(s.layer, s.evidence_basis_id, window_anchor=inputs.server_received_at)
        for s in inputs.signals
    )
    bad_inputs = dataclasses.replace(inputs, signals=fraud_signals)
    ports = make_ports()
    policies = make_policies(registration, grs_bundle="eligible")

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is not OutcomeStatus.PASS


def test_insufficient_repeats_is_undetermined() -> None:
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    sig = inputs.signals[0]
    short_cell = CellObservation(
        repeat_values=(20.0,),
        timestamps=(inputs.server_received_at + timedelta(days=1),),
    )
    short_sig = sig.model_copy(update={"post_treatment": short_cell})
    new_signals = (short_sig, *inputs.signals[1:])
    bad_inputs = dataclasses.replace(inputs, signals=new_signals)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.INSUFFICIENT_REPEATS in outcome.reason_codes


def test_missing_control_cell_is_undetermined() -> None:
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    sig = inputs.signals[0]
    no_control_sig = sig.model_copy(update={"baseline_control": None, "post_control": None})
    new_signals = (no_control_sig, *inputs.signals[1:])
    bad_inputs = dataclasses.replace(inputs, signals=new_signals)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.MISSING_CONTROL in outcome.reason_codes


def test_single_qualifying_layer_is_fail_not_pass() -> None:
    """wave5-plan.md E4: 1-layer improvement != PASS."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=1)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.status is OutcomeStatus.FAIL
    assert ReasonCode.SINGLE_LAYER_ONLY in outcome.reason_codes
    assert len(outcome.qualifying_layers) == 1


def test_two_qualifying_layers_pass() -> None:
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.status is OutcomeStatus.PASS
    assert len(outcome.qualifying_layers) >= 2


def test_duplicate_evidence_basis_counts_once() -> None:
    """Two signals sharing ONE evidence_basis_id must count as ONE
    independent layer — reused basis is not a second independent layer."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=1)
    sig = inputs.signals[0]
    duplicate_basis_sig = sig.model_copy(update={"layer": "prominence"})
    new_signals = (*inputs.signals, duplicate_basis_sig)
    bad_inputs = dataclasses.replace(inputs, signals=new_signals)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    # Still only ONE independent qualifying layer (duplicate basis dedups).
    assert outcome.status is OutcomeStatus.FAIL
    assert ReasonCode.SINGLE_LAYER_ONLY in outcome.reason_codes

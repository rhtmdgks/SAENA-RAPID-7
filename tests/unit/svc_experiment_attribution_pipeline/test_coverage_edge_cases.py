"""Discriminating fixtures for branches not exercised by the main scenario
files: adapter drift (an out-of-vocabulary layer), missing per-observation
evidence metadata (an honest RAW_OBSERVATION_REF gap), the naive-datetime
`computed_at` fallback, and `PipelineError.to_dict()`'s log-safe shape."""

from __future__ import annotations

import dataclasses

from pipeline_factories import make_happy_path_inputs, make_policies, make_ports
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement
from saena_experiment_attribution.pipeline.errors import PipelineError
from saena_experiment_attribution.pipeline.orchestrator import (
    _deterministic_computed_at,
    _final_status,
    _RunState,
)


def test_out_of_vocabulary_layer_is_adapter_drift_undetermined() -> None:
    """A DiD signal fed by an upstream producer using a layer name outside
    the closed OutcomeLayer vocabulary (e.g. the forbidden 'conversion')
    cannot be scored by the gate — surfaced as adapter drift, not a crash."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    bad_layer_signal = inputs.signals[0].model_copy(update={"layer": "conversion"})
    new_signals = (bad_layer_signal, *inputs.signals[1:])
    bad_inputs = dataclasses.replace(inputs, signals=new_signals)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.OBSERVATION_ADAPTER_DRIFT in outcome.reason_codes


def test_missing_per_observation_evidence_metadata_is_honest_gap() -> None:
    """When the caller supplies no per-observation `EvidenceMetadata` for a
    signal's evidence_basis_id, the pipeline does NOT synthesize/forge one —
    the observation-kind entry (and therefore RAW_OBSERVATION_REF) is simply
    absent, surfacing as MISSING_RAW_EVIDENCE_REF + an incomplete bundle."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    bad_inputs = dataclasses.replace(
        inputs, baseline_evidence=(), treatment_evidence=(), control_evidence=()
    )
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.MISSING_RAW_EVIDENCE_REF in outcome.reason_codes
    assert outcome.evidence_bundle_complete is False


def test_deterministic_computed_at_normalizes_naive_datetime() -> None:
    """A naive `evaluation_at` (should not occur once `window_complete`'s own
    naive-datetime guard has run upstream, but this helper is defensive) is
    normalized to UTC rather than silently misinterpreted."""
    inputs, _registration = make_happy_path_inputs()
    naive_inputs = dataclasses.replace(
        inputs, evaluation_at=inputs.evaluation_at.replace(tzinfo=None)
    )

    result = _deterministic_computed_at(naive_inputs)

    assert result.tzinfo is not None
    assert result == inputs.evaluation_at.replace(tzinfo=result.tzinfo)


def test_pipeline_error_to_dict_is_log_safe() -> None:
    error = PipelineError("something went wrong", context={"tenant_id": "acme-co"})

    payload = error.to_dict()

    assert payload["error_code"] == "saena.experiment_attribution.pipeline.error"
    assert payload["message"] == "something went wrong"
    assert payload["tenant_id"] == "acme-co"


def test_final_status_with_no_b_gate_decision_is_undetermined() -> None:
    """`_final_status` on a `_RunState` that never got a B-gate decision
    (should not occur via `run_measurement`, which always calls `_run_b_gate`
    before `_final_status` — this is the defensive fallback for the type-level
    `BGateDecision | None`) must be UNDETERMINED, never PASS/FAIL."""
    state = _RunState()

    assert _final_status(state) is OutcomeStatus.UNDETERMINED

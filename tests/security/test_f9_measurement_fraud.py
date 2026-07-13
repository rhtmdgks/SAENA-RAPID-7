"""F-9 Measurement fraud (k3s spec §10 row 9, failure-mode matrix `F-9`).

Fixture: "raw citation count grows but control too → B-layer success not
granted". See `measurement_fraud.py`'s module docstring for the missing-
owner note and the pure evaluator this test wires against.
"""

from __future__ import annotations

from measurement_fraud import (
    MIN_INDEPENDENT_SIGNALS,
    BLayerVerdict,
    MeasurementSignal,
    evaluate_b_layer_success,
)


def test_raw_citation_growth_with_matching_control_growth_denies_b_layer_success() -> None:
    """The literal fixture: treatment citation count grew by 40, but so did
    the control's — net-of-control lift is zero, not a real effect."""
    signals = (
        MeasurementSignal("citation_count", treatment_raw_delta=40.0, control_raw_delta=40.0),
        MeasurementSignal("click_through_rate", treatment_raw_delta=0.02, control_raw_delta=0.02),
    )
    verdict = evaluate_b_layer_success(signals)
    assert verdict.granted is False
    assert "citation_count" in verdict.reason
    assert "click_through_rate" in verdict.reason
    assert verdict.net_lifts == {"citation_count": 0.0, "click_through_rate": 0.0}


def test_raw_citation_growth_where_control_grew_even_more_denies_b_layer_success() -> None:
    """A harsher variant of the same fraud shape: control outgrew treatment
    — a NEGATIVE net-of-control lift, still zero tolerance."""
    signals = (
        MeasurementSignal("citation_count", treatment_raw_delta=40.0, control_raw_delta=55.0),
        MeasurementSignal("absorption_rate", treatment_raw_delta=0.10, control_raw_delta=0.10),
    )
    verdict = evaluate_b_layer_success(signals)
    assert verdict.granted is False
    assert verdict.net_lifts["citation_count"] < 0


def test_single_positive_signal_alone_is_insufficient_even_with_real_lift() -> None:
    """A single genuinely-positive signal still does not grant success —
    >=2 independent signals must agree (mission instruction)."""
    signals = (
        MeasurementSignal("citation_count", treatment_raw_delta=40.0, control_raw_delta=10.0),
    )
    verdict = evaluate_b_layer_success(signals)
    assert verdict.granted is False
    assert str(MIN_INDEPENDENT_SIGNALS) in verdict.reason


def test_one_real_signal_and_one_control_matched_signal_still_denies_success() -> None:
    """Partial fraud: one signal shows a genuine causal lift, but a SECOND
    signal is the same "raw grows, control grows too" shape — zero
    tolerance on any single unaccounted-for signal blocks the whole
    verdict, it is not averaged away by the signal that IS real."""
    signals = (
        MeasurementSignal("citation_count", treatment_raw_delta=40.0, control_raw_delta=10.0),
        MeasurementSignal("click_through_rate", treatment_raw_delta=0.05, control_raw_delta=0.05),
    )
    verdict = evaluate_b_layer_success(signals)
    assert verdict.granted is False
    assert "click_through_rate" in verdict.reason
    assert "citation_count" not in verdict.reason


def test_two_independent_signals_with_genuine_net_of_control_lift_grants_success() -> None:
    """Negative control for the evaluator itself: a REAL, control-accounted
    lift across >=2 independent signals is grantable — proves this is an
    actual causal check, not a blanket denial."""
    signals = (
        MeasurementSignal("citation_count", treatment_raw_delta=40.0, control_raw_delta=10.0),
        MeasurementSignal("click_through_rate", treatment_raw_delta=0.05, control_raw_delta=0.01),
    )
    verdict = evaluate_b_layer_success(signals)
    assert verdict.granted is True
    assert isinstance(verdict, BLayerVerdict)
    assert verdict.net_lifts["citation_count"] == 30.0


def test_evaluator_is_deterministic_across_repeated_calls() -> None:
    signals = (
        MeasurementSignal("citation_count", treatment_raw_delta=40.0, control_raw_delta=10.0),
        MeasurementSignal("click_through_rate", treatment_raw_delta=0.05, control_raw_delta=0.01),
    )
    assert evaluate_b_layer_success(signals) == evaluate_b_layer_success(signals)

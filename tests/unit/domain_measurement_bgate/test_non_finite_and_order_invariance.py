"""Adversarial non-finite-input + input-order-invariance tests (critic rework).

Guard mutation anchors:
- removing ``allow_inf_nan=False`` from any numeric field flips the
  construction-rejection tests;
- removing the defensive ``math.isfinite`` re-check in ``decide_b_verdict``
  flips the ``model_construct``-bypass tests (forged PASS would come back);
- reverting maximum bipartite matching to greedy basis-keyed assignment flips
  the permutation property test.
"""

from __future__ import annotations

import itertools
import math

import pytest
from pydantic import ValidationError
from saena_domain.measurement.b_gate import (
    BGateDecision,
    BVerdict,
    PolicyProvenance,
    SignalResult,
    decide_b_verdict,
)
from saena_domain.measurement.outcome_layer import OutcomeLayer
from saena_domain.measurement.reason_codes import ReasonCode

from .conftest import (
    healthy_window,
    intact_evidence,
    production_policy,
    signal,
    two_independent_positive,
)

NON_FINITE = (float("nan"), float("inf"), float("-inf"))
NUMERIC_FIELDS = ("treatment_raw_delta", "control_raw_delta", "net_of_control_lift")


def _forged_signal(layer: OutcomeLayer, basis: str, **overrides: float) -> SignalResult:
    """Bypass pydantic validation (model_construct) to forge non-finite values —
    the exact vector the defensive gate-time check exists for."""
    fields: dict[str, object] = {
        "layer": layer,
        "evidence_basis_id": basis,
        "treatment_raw_delta": 1.0,
        "control_raw_delta": 0.0,
        "net_of_control_lift": 1.0,
        "has_control_adjusted_lift": True,
        "sufficient_data": True,
        "has_raw_evidence_ref": True,
    }
    fields.update(overrides)
    return SignalResult.model_construct(**fields)


# --------------------------------------------------------------------------
# Construction-time rejection (layer 1: pydantic allow_inf_nan=False)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("field", NUMERIC_FIELDS)
@pytest.mark.parametrize("bad", NON_FINITE, ids=("nan", "+inf", "-inf"))
def test_signal_construction_rejects_non_finite(field: str, bad: float) -> None:
    kwargs: dict[str, object] = {
        "layer": OutcomeLayer.CITATION,
        "evidence_basis_id": "basis-A",
        "treatment_raw_delta": 1.0,
        "control_raw_delta": 0.0,
        "net_of_control_lift": 1.0,
    }
    kwargs[field] = bad
    with pytest.raises(ValidationError):
        SignalResult(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_confidence",
    [float("nan"), float("inf"), float("-inf"), 1.5, -0.1],
    ids=("nan", "+inf", "-inf", "gt-1", "lt-0"),
)
def test_decision_confidence_rejects_non_finite_and_out_of_range(
    bad_confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        BGateDecision(
            verdict=BVerdict.PASS,
            reason_codes=(),
            raw_view=(),
            control_adjusted_view=(),
            qualifying_layers=(),
            confidence=bad_confidence,
            policy_version="grs-v1",
            policy_hash="sha256:" + "0" * 64,
            policy_provenance=PolicyProvenance.PRODUCTION,
            is_production=True,
        )


# --------------------------------------------------------------------------
# Gate-time defensive rejection (layer 2: model_construct bypass)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("field", NUMERIC_FIELDS)
@pytest.mark.parametrize("bad", NON_FINITE, ids=("nan", "+inf", "-inf"))
def test_forged_non_finite_field_undetermined_never_pass(field: str, bad: float) -> None:
    forged = _forged_signal(OutcomeLayer.CITATION, "basis-A", **{field: bad})
    good = signal(OutcomeLayer.PROMINENCE, basis="basis-B")
    decision = decide_b_verdict(
        (forged, good), intact_evidence(), healthy_window(), production_policy()
    )
    assert decision.verdict is not BVerdict.PASS
    assert decision.verdict is BVerdict.UNDETERMINED
    assert ReasonCode.NON_FINITE_INPUT in decision.reason_codes
    # The forged signal contributes to NO view and never qualifies.
    assert OutcomeLayer.CITATION not in decision.raw_view
    assert OutcomeLayer.CITATION not in decision.control_adjusted_view
    assert OutcomeLayer.CITATION not in decision.qualifying_layers


def test_two_distinct_layer_nan_signals_never_pass() -> None:
    # The original forged-PASS reproducer: two distinct layers, distinct
    # bases, NaN/inf lifts — must be UNDETERMINED, never PASS/confidence 1.0.
    forged = (
        _forged_signal(OutcomeLayer.CITATION, "basis-A", net_of_control_lift=float("nan")),
        _forged_signal(OutcomeLayer.PROMINENCE, "basis-B", net_of_control_lift=float("nan")),
    )
    decision = decide_b_verdict(forged, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is BVerdict.UNDETERMINED
    assert decision.qualifying_layers == ()
    assert decision.confidence == 0.0
    assert ReasonCode.NON_FINITE_INPUT in decision.reason_codes


def test_nan_plus_inf_mixed_forgery_never_pass() -> None:
    forged = (
        _forged_signal(OutcomeLayer.CITATION, "basis-A", net_of_control_lift=float("nan")),
        _forged_signal(OutcomeLayer.PROMINENCE, "basis-B", net_of_control_lift=float("inf")),
    )
    decision = decide_b_verdict(forged, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is BVerdict.UNDETERMINED
    assert ReasonCode.NON_FINITE_INPUT in decision.reason_codes


# --------------------------------------------------------------------------
# Internal invariant: qualifying ⊆ control_adjusted_view
# --------------------------------------------------------------------------
def _assert_invariant(decision: BGateDecision) -> None:
    assert set(decision.qualifying_layers) <= set(decision.control_adjusted_view), (
        "a qualifying layer invisible to the control-adjusted view is forged"
    )


def test_invariant_qualifying_layers_visible_in_control_adjusted_view() -> None:
    cases = (
        two_independent_positive(),
        (signal(OutcomeLayer.CITATION, basis="basis-A"),),
        (
            _forged_signal(OutcomeLayer.CITATION, "basis-A", net_of_control_lift=float("nan")),
            signal(OutcomeLayer.PROMINENCE, basis="basis-B"),
        ),
        (
            signal(OutcomeLayer.CITATION, basis="basis-A", net_of_control_lift=0.0),
            signal(OutcomeLayer.REFERRAL, basis="basis-C", net_of_control_lift=2.0),
        ),
        (),
    )
    for per_signal_results in cases:
        _assert_invariant(
            decide_b_verdict(
                per_signal_results, intact_evidence(), healthy_window(), production_policy()
            )
        )


# --------------------------------------------------------------------------
# Input-order invariance: maximum matching, never greedy
# --------------------------------------------------------------------------
def test_permutation_invariance_shared_basis_matching() -> None:
    # Critic-1 reproducer: CITATION has two bases, PROMINENCE shares one of
    # them. A maximum matching always finds 2 independent layers
    # (CITATION→b2, PROMINENCE→b1) — a greedy basis-keyed assignment gave
    # PASS or FAIL depending on tuple order.
    signals = [
        signal(OutcomeLayer.CITATION, basis="b1"),
        signal(OutcomeLayer.CITATION, basis="b2"),
        signal(OutcomeLayer.PROMINENCE, basis="b1"),
    ]
    decisions = [
        decide_b_verdict(tuple(perm), intact_evidence(), healthy_window(), production_policy())
        for perm in itertools.permutations(signals)
    ]
    first = decisions[0]
    assert first.verdict is BVerdict.PASS
    assert first.qualifying_layers == (OutcomeLayer.CITATION, OutcomeLayer.PROMINENCE)
    for other in decisions[1:]:
        assert other == first  # identical verdict, layers, codes, views


def test_permutation_invariance_mixed_qualities() -> None:
    signals = [
        signal(OutcomeLayer.CITATION, basis="b1", net_of_control_lift=0.0),
        signal(OutcomeLayer.PROMINENCE, basis="b2"),
        signal(OutcomeLayer.REFERRAL, basis="b2"),  # shares b2
        signal(OutcomeLayer.DISCOVERY, basis="b3", net_of_control_lift=-1.0),
    ]
    decisions = [
        decide_b_verdict(tuple(perm), intact_evidence(), healthy_window(), production_policy())
        for perm in itertools.permutations(signals)
    ]
    first = decisions[0]
    for other in decisions[1:]:
        assert other == first


def test_matching_is_maximum_not_greedy_three_layers() -> None:
    # Chain structure: A:{b1}, B:{b1,b2}, C:{b2,b3} — maximum matching is 3
    # (A→b1, B→b2, C→b3); several greedy orders find only 2.
    signals = (
        signal(OutcomeLayer.CITATION, basis="b1"),
        signal(OutcomeLayer.PROMINENCE, basis="b1"),
        signal(OutcomeLayer.PROMINENCE, basis="b2"),
        signal(OutcomeLayer.REFERRAL, basis="b2"),
        signal(OutcomeLayer.REFERRAL, basis="b3"),
    )
    decision = decide_b_verdict(signals, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is BVerdict.PASS
    assert decision.qualifying_layers == (
        OutcomeLayer.CITATION,
        OutcomeLayer.PROMINENCE,
        OutcomeLayer.REFERRAL,
    )


def test_math_isfinite_is_the_defensive_check() -> None:
    # Executable pin that the defensive layer really is isfinite-based: a
    # finite extreme value is fine, non-finite is not.
    assert math.isfinite(1e308)
    ok = signal(OutcomeLayer.CITATION, basis="b1", net_of_control_lift=1e308)
    decision = decide_b_verdict((ok,), intact_evidence(), healthy_window(), production_policy())
    assert ReasonCode.NON_FINITE_INPUT not in decision.reason_codes

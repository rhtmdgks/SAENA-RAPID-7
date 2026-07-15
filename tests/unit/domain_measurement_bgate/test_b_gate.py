"""Discriminating B-gate tests (w5-06, E4 + guard mutation).

Structured so removal of each core rule flips at least one test:
- ≥2-independent-layer rule            → test_two_independent_layers_pass /
                                          test_single_qualifying_layer_fails
- duplicate-basis / duplicate-layer dedup → test_cloned_single_layer_two_entries_*
- strict positivity (net-of-control)   → test_zero_lift_not_qualifying /
                                          test_negative_lift_not_qualifying /
                                          test_raw_up_control_equal_never_pass
- fail-closed evidence                 → test_manifest_hash_mismatch_undetermined /
                                          test_missing_raw_refs_undetermined
- 3-way verdict (never collapsed)      → the three verdict-pinning tests below
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError
from saena_domain.measurement.b_gate import (
    BGateDecision,
    BVerdict,
    PolicyProvenance,
    decide_b_verdict,
)
from saena_domain.measurement.outcome_layer import OutcomeLayer
from saena_domain.measurement.reason_codes import ReasonCode

from .conftest import (
    fixture_policy,
    healthy_window,
    intact_evidence,
    production_policy,
    signal,
    two_independent_positive,
)


# --------------------------------------------------------------------------
# PASS path
# --------------------------------------------------------------------------
def test_two_independent_layers_pass() -> None:
    decision = decide_b_verdict(
        two_independent_positive(),
        intact_evidence(),
        healthy_window(),
        production_policy(),
    )
    assert decision.verdict is BVerdict.PASS
    assert decision.qualifying_layers == (OutcomeLayer.CITATION, OutcomeLayer.PROMINENCE)
    assert decision.reason_codes == ()
    assert decision.confidence == 1.0
    assert decision.is_production is True


def test_pass_decision_is_frozen() -> None:
    decision = decide_b_verdict(
        two_independent_positive(),
        intact_evidence(),
        healthy_window(),
        production_policy(),
    )
    assert isinstance(decision, BGateDecision)
    with pytest.raises(ValidationError):
        decision.verdict = BVerdict.FAIL  # type: ignore[misc]


def test_decision_carries_both_views_and_policy_passthrough() -> None:
    decision = decide_b_verdict(
        two_independent_positive(),
        intact_evidence(),
        healthy_window(),
        production_policy(version="grs-v9", hash="sha256:" + "a" * 64),
    )
    assert decision.raw_view == (OutcomeLayer.CITATION, OutcomeLayer.PROMINENCE)
    assert decision.control_adjusted_view == (
        OutcomeLayer.CITATION,
        OutcomeLayer.PROMINENCE,
    )
    assert decision.policy_version == "grs-v9"
    assert decision.policy_hash == "sha256:" + "a" * 64
    assert decision.policy_provenance is PolicyProvenance.PRODUCTION


# --------------------------------------------------------------------------
# ≥2 rule + single-layer FAIL (data sufficient, effect insufficient)
# --------------------------------------------------------------------------
def test_single_qualifying_layer_fails() -> None:
    decision = decide_b_verdict(
        (signal(OutcomeLayer.CITATION, basis="basis-A"),),
        intact_evidence(),
        healthy_window(),
        production_policy(),
    )
    # data was sufficient, effect insufficient → FAIL not UNDETERMINED.
    assert decision.verdict is BVerdict.FAIL
    assert ReasonCode.SINGLE_LAYER_ONLY in decision.reason_codes
    assert decision.qualifying_layers == (OutcomeLayer.CITATION,)


def test_single_layer_is_fail_not_undetermined() -> None:
    decision = decide_b_verdict(
        (signal(OutcomeLayer.REFERRAL, basis="basis-Z"),),
        intact_evidence(),
        healthy_window(),
        production_policy(),
    )
    assert decision.verdict is not BVerdict.UNDETERMINED
    assert decision.verdict is BVerdict.FAIL


# --------------------------------------------------------------------------
# Duplicate-basis / duplicate-layer dedup → single-layer, NOT PASS
# --------------------------------------------------------------------------
def test_cloned_single_layer_two_entries_shared_basis_not_pass() -> None:
    # Same layer filed twice with the SAME evidence_basis_id → counts ONCE.
    cloned = (
        signal(OutcomeLayer.CITATION, basis="basis-shared"),
        signal(OutcomeLayer.CITATION, basis="basis-shared"),
    )
    decision = decide_b_verdict(cloned, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is not BVerdict.PASS
    assert decision.verdict is BVerdict.FAIL
    assert ReasonCode.SINGLE_LAYER_ONLY in decision.reason_codes
    assert ReasonCode.DUPLICATE_EVIDENCE_BASIS in decision.reason_codes
    assert decision.qualifying_layers == (OutcomeLayer.CITATION,)


def test_same_layer_distinct_bases_still_one_layer_not_pass() -> None:
    # Same LAYER twice, DIFFERENT bases → still one independent layer.
    dup_layer = (
        signal(OutcomeLayer.CITATION, basis="basis-A"),
        signal(OutcomeLayer.CITATION, basis="basis-B"),
    )
    decision = decide_b_verdict(dup_layer, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is BVerdict.FAIL
    assert decision.qualifying_layers == (OutcomeLayer.CITATION,)
    assert ReasonCode.SINGLE_LAYER_ONLY in decision.reason_codes


def test_two_layers_sharing_one_basis_count_once() -> None:
    # Two DIFFERENT layers but a SHARED evidence_basis_id are not independent.
    shared = (
        signal(OutcomeLayer.CITATION, basis="basis-shared"),
        signal(OutcomeLayer.PROMINENCE, basis="basis-shared"),
    )
    decision = decide_b_verdict(shared, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is not BVerdict.PASS
    assert ReasonCode.DUPLICATE_EVIDENCE_BASIS in decision.reason_codes
    assert len(decision.qualifying_layers) == 1


# --------------------------------------------------------------------------
# Strict positivity (net-of-control)
# --------------------------------------------------------------------------
def test_zero_lift_not_qualifying() -> None:
    signals = (
        signal(OutcomeLayer.CITATION, basis="basis-A", net_of_control_lift=0.0),
        signal(OutcomeLayer.PROMINENCE, basis="basis-B", net_of_control_lift=2.0),
    )
    decision = decide_b_verdict(signals, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is BVerdict.FAIL
    assert decision.qualifying_layers == (OutcomeLayer.PROMINENCE,)
    assert ReasonCode.NEGATIVE_OR_INCONCLUSIVE_LIFT in decision.reason_codes


def test_negative_lift_not_qualifying() -> None:
    signals = (
        signal(OutcomeLayer.CITATION, basis="basis-A", net_of_control_lift=-1.0),
        signal(OutcomeLayer.PROMINENCE, basis="basis-B", net_of_control_lift=-0.5),
    )
    decision = decide_b_verdict(signals, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is BVerdict.FAIL
    assert decision.qualifying_layers == ()
    assert ReasonCode.NEGATIVE_OR_INCONCLUSIVE_LIFT in decision.reason_codes


def test_raw_up_control_equal_never_pass_fraud_fixture() -> None:
    # F-9: every layer's RAW treatment count grew (treatment_raw_delta > 0)
    # but control grew equally → net lift 0. Data sufficient → FAIL, never PASS.
    fraud = (
        signal(
            OutcomeLayer.CITATION,
            basis="basis-A",
            treatment_raw_delta=5.0,
            control_raw_delta=5.0,
            net_of_control_lift=0.0,
        ),
        signal(
            OutcomeLayer.PROMINENCE,
            basis="basis-B",
            treatment_raw_delta=3.0,
            control_raw_delta=3.0,
            net_of_control_lift=0.0,
        ),
        signal(
            OutcomeLayer.REFERRAL,
            basis="basis-C",
            treatment_raw_delta=2.0,
            control_raw_delta=2.0,
            net_of_control_lift=0.0,
        ),
    )
    decision = decide_b_verdict(fraud, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is not BVerdict.PASS
    assert decision.verdict is BVerdict.FAIL
    assert decision.qualifying_layers == ()
    assert ReasonCode.NEGATIVE_OR_INCONCLUSIVE_LIFT in decision.reason_codes
    # The F-9 contrast the two views exist to show (k3s §9.2:485): the raw
    # view SEES the raw movement, the control-adjusted view does NOT — and
    # the strict-positivity comparison (never >=) keeps the latter empty.
    assert decision.raw_view == (
        OutcomeLayer.CITATION,
        OutcomeLayer.PROMINENCE,
        OutcomeLayer.REFERRAL,
    )
    assert decision.control_adjusted_view == ()


def test_raw_view_reflects_actual_raw_movement_not_lift_sign() -> None:
    # Positive lift but NO raw treatment movement (control collapsed):
    # in control-adjusted view, NOT in raw view.
    signals = (
        signal(
            OutcomeLayer.CITATION,
            basis="basis-A",
            treatment_raw_delta=0.0,
            control_raw_delta=-2.0,
            net_of_control_lift=2.0,
        ),
    )
    decision = decide_b_verdict(signals, intact_evidence(), healthy_window(), production_policy())
    assert OutcomeLayer.CITATION not in decision.raw_view
    assert OutcomeLayer.CITATION in decision.control_adjusted_view


def test_zero_and_negative_lift_excluded_from_control_adjusted_view() -> None:
    signals = (
        signal(OutcomeLayer.CITATION, basis="basis-A", net_of_control_lift=0.0),
        signal(OutcomeLayer.PROMINENCE, basis="basis-B", net_of_control_lift=-1.0),
        signal(OutcomeLayer.REFERRAL, basis="basis-C", net_of_control_lift=2.0),
    )
    decision = decide_b_verdict(signals, intact_evidence(), healthy_window(), production_policy())
    # Only the strictly-positive layer is in the control-adjusted view.
    assert decision.control_adjusted_view == (OutcomeLayer.REFERRAL,)


def test_raw_increase_without_control_adjustment_not_qualifying() -> None:
    signals = (
        signal(
            OutcomeLayer.CITATION,
            basis="basis-A",
            has_control_adjusted_lift=False,
        ),
        signal(OutcomeLayer.PROMINENCE, basis="basis-B", net_of_control_lift=3.0),
    )
    decision = decide_b_verdict(signals, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is BVerdict.FAIL
    # raw view sees the citation increase, control-adjusted view does not.
    assert OutcomeLayer.CITATION in decision.raw_view
    assert OutcomeLayer.CITATION not in decision.control_adjusted_view
    assert ReasonCode.NO_CONTROL_ADJUSTED_LIFT in decision.reason_codes
    assert decision.qualifying_layers == (OutcomeLayer.PROMINENCE,)


# --------------------------------------------------------------------------
# Fail-closed evidence → UNDETERMINED
# --------------------------------------------------------------------------
def test_manifest_hash_mismatch_undetermined() -> None:
    from saena_domain.measurement.b_gate import EvidenceCheck

    decision = decide_b_verdict(
        two_independent_positive(),
        EvidenceCheck(manifest_hash_ok=False, raw_refs_present=True),
        healthy_window(),
        production_policy(),
    )
    assert decision.verdict is BVerdict.UNDETERMINED
    assert ReasonCode.EVIDENCE_HASH_MISMATCH in decision.reason_codes


def test_missing_raw_refs_undetermined() -> None:
    from saena_domain.measurement.b_gate import EvidenceCheck

    decision = decide_b_verdict(
        two_independent_positive(),
        EvidenceCheck(manifest_hash_ok=True, raw_refs_present=False),
        healthy_window(),
        production_policy(),
    )
    assert decision.verdict is BVerdict.UNDETERMINED
    assert ReasonCode.MISSING_RAW_EVIDENCE_REF in decision.reason_codes


def test_broken_evidence_never_pass_even_with_two_positive_layers() -> None:
    from saena_domain.measurement.b_gate import EvidenceCheck

    decision = decide_b_verdict(
        two_independent_positive(),
        EvidenceCheck(manifest_hash_ok=False, raw_refs_present=False),
        healthy_window(),
        production_policy(),
    )
    assert decision.verdict is not BVerdict.PASS
    assert decision.verdict is BVerdict.UNDETERMINED


# --------------------------------------------------------------------------
# Window / deployment / design insufficiency → UNDETERMINED (each code pinned)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("field", "expected_code"),
    [
        ("complete", ReasonCode.WINDOW_INCOMPLETE),
        ("deployment_confirmed", ReasonCode.DEPLOYMENT_UNCONFIRMED),
    ],
)
def test_positive_sense_window_flags_false_undetermined(
    field: str, expected_code: ReasonCode
) -> None:
    from saena_domain.measurement.b_gate import WindowState

    kwargs = {"complete": True, "deployment_confirmed": True}
    kwargs[field] = False
    decision = decide_b_verdict(
        two_independent_positive(),
        intact_evidence(),
        WindowState(**kwargs),
        production_policy(),
    )
    assert decision.verdict is BVerdict.UNDETERMINED
    assert expected_code in decision.reason_codes


@pytest.mark.parametrize(
    ("flag", "expected_code"),
    [
        ("deployment_late", ReasonCode.DEPLOYMENT_LATE),
        ("contamination", ReasonCode.TREATMENT_CONTROL_CONTAMINATION),
        ("adapter_drift", ReasonCode.OBSERVATION_ADAPTER_DRIFT),
        ("missing_baseline", ReasonCode.MISSING_BASELINE),
        ("missing_control", ReasonCode.MISSING_CONTROL),
        ("insufficient_repeats", ReasonCode.INSUFFICIENT_REPEATS),
    ],
)
def test_problem_flags_force_undetermined(flag: str, expected_code: ReasonCode) -> None:
    from saena_domain.measurement.b_gate import WindowState

    window = WindowState(complete=True, deployment_confirmed=True, **{flag: True})
    decision = decide_b_verdict(
        two_independent_positive(),
        intact_evidence(),
        window,
        production_policy(),
    )
    assert decision.verdict is BVerdict.UNDETERMINED
    assert expected_code in decision.reason_codes


def test_late_deployment_never_pass() -> None:
    from saena_domain.measurement.b_gate import WindowState

    decision = decide_b_verdict(
        two_independent_positive(),
        intact_evidence(),
        WindowState(complete=True, deployment_confirmed=True, deployment_late=True),
        production_policy(),
    )
    assert decision.verdict is not BVerdict.PASS


def test_signal_insufficient_data_forces_undetermined() -> None:
    signals = (
        signal(OutcomeLayer.CITATION, basis="basis-A"),
        signal(OutcomeLayer.PROMINENCE, basis="basis-B", sufficient_data=False),
    )
    decision = decide_b_verdict(signals, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is BVerdict.UNDETERMINED
    assert ReasonCode.INSUFFICIENT_REPEATS in decision.reason_codes


def test_signal_missing_raw_ref_forces_undetermined() -> None:
    signals = (
        signal(OutcomeLayer.CITATION, basis="basis-A"),
        signal(OutcomeLayer.PROMINENCE, basis="basis-B", has_raw_evidence_ref=False),
    )
    decision = decide_b_verdict(signals, intact_evidence(), healthy_window(), production_policy())
    assert decision.verdict is BVerdict.UNDETERMINED
    assert ReasonCode.MISSING_RAW_EVIDENCE_REF in decision.reason_codes


# --------------------------------------------------------------------------
# 3-way verdict distinctness — each value reachable and distinct
# --------------------------------------------------------------------------
def test_three_verdict_values_distinct() -> None:
    assert len({BVerdict.PASS, BVerdict.FAIL, BVerdict.UNDETERMINED}) == 3


def test_each_verdict_value_is_reachable() -> None:
    from saena_domain.measurement.b_gate import WindowState

    a_pass = decide_b_verdict(
        two_independent_positive(),
        intact_evidence(),
        healthy_window(),
        production_policy(),
    )
    a_fail = decide_b_verdict(
        (signal(OutcomeLayer.CITATION, basis="basis-A"),),
        intact_evidence(),
        healthy_window(),
        production_policy(),
    )
    an_undet = decide_b_verdict(
        two_independent_positive(),
        intact_evidence(),
        WindowState(complete=False, deployment_confirmed=True),
        production_policy(),
    )
    assert {a_pass.verdict, a_fail.verdict, an_undet.verdict} == {
        BVerdict.PASS,
        BVerdict.FAIL,
        BVerdict.UNDETERMINED,
    }


# --------------------------------------------------------------------------
# No weight parameter (P0 weights forbidden)
# --------------------------------------------------------------------------
def test_no_weight_parameter() -> None:
    params = set(inspect.signature(decide_b_verdict).parameters)
    forbidden = {p for p in params if "weight" in p.lower()}
    assert not forbidden, f"gate must not accept weight params: {forbidden}"
    assert params == {
        "per_signal_results",
        "evidence_check",
        "window_state",
        "policy",
    }


# --------------------------------------------------------------------------
# Provenance separation: test_fixture ⇒ not production
# --------------------------------------------------------------------------
def test_test_fixture_provenance_marks_non_production() -> None:
    decision = decide_b_verdict(
        two_independent_positive(),
        intact_evidence(),
        healthy_window(),
        fixture_policy(),
    )
    # Mechanism can PASS but the decision is explicitly non-production.
    assert decision.verdict is BVerdict.PASS
    assert decision.is_production is False
    assert decision.policy_provenance is PolicyProvenance.TEST_FIXTURE


def test_production_provenance_marks_production() -> None:
    decision = decide_b_verdict(
        two_independent_positive(),
        intact_evidence(),
        healthy_window(),
        production_policy(),
    )
    assert decision.is_production is True


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------
def test_deterministic_repeated_calls_equal() -> None:
    args = (
        two_independent_positive(),
        intact_evidence(),
        healthy_window(),
        production_policy(),
    )
    d1 = decide_b_verdict(*args)
    d2 = decide_b_verdict(*args)
    assert d1 == d2


def test_reason_codes_sorted_deterministically() -> None:
    from saena_domain.measurement.b_gate import WindowState

    window = WindowState(
        complete=False,
        deployment_confirmed=False,
        contamination=True,
        adapter_drift=True,
    )
    decision = decide_b_verdict(
        two_independent_positive(),
        intact_evidence(),
        window,
        production_policy(),
    )
    values = [c.value for c in decision.reason_codes]
    assert values == sorted(values)


def test_empty_signals_fails_not_pass() -> None:
    decision = decide_b_verdict(
        (),
        intact_evidence(),
        healthy_window(),
        production_policy(),
    )
    assert decision.verdict is BVerdict.FAIL
    assert decision.qualifying_layers == ()

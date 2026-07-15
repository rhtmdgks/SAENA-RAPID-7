"""Discriminating tests for the deterministic per-signal DiD engine (w5-05).

Written BEFORE the implementation (TDD). Each named FP/FN fixture from the
w5-05 mission is a distinct test:

  (a) known synthetic effect +X recovered exactly
  (b) zero effect -> lift 0, not positive
  (c) common trend both arms +Y -> lift 0 (market drift removed)
  (d) treatment raw +5 with control +5 -> lift 0 (F-9 / k3s §10:513 fraud parity)
  (e) negative lift reported negative
  (f) tiny-n -> insufficient, not a verdict
  (g) None/NaN cells -> insufficient, never silently dropped

Plus: raw AND control-adjusted views both exposed; insufficiency codes
(missing_baseline / missing_control / insufficient_repeats); late-observation
exclusion; unequal-repeat mean normalization with sample counts; determinism
(byte-identical canonical output, permutation-invariant); leave-one-out sign
stability; min detectable margin vs policy.effect_threshold.
"""

from __future__ import annotations

import math
from datetime import datetime

import pytest
from saena_domain.measurement.did import (
    InsufficiencyCode,
    compute_did,
)

from .conftest import LATE, WINDOW_END, WINDOW_START, cell, make_policy, series

POLICY = make_policy(min_repeats=3, effect_threshold=1.0)


# --------------------------------------------------------------------------
# Core FP/FN recovery fixtures (a)-(e)
# --------------------------------------------------------------------------


def test_a_known_synthetic_effect_recovered_exactly() -> None:
    # treatment: 10 -> 20 (+10); control: 10 -> 12 (+2). Net-of-control = +8.
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=cell(20.0),
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    r = compute_did((s,), POLICY)
    sig = r.signals[0]
    assert not sig.insufficient
    assert sig.treatment_raw_delta == pytest.approx(10.0)
    assert sig.control_raw_delta == pytest.approx(2.0)
    assert sig.net_of_control_lift == pytest.approx(8.0)


def test_b_zero_effect_is_zero_not_positive() -> None:
    # nothing moves anywhere
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=cell(10.0),
        baseline_control=cell(10.0),
        post_control=cell(10.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.net_of_control_lift == pytest.approx(0.0)
    assert sig.net_of_control_lift == 0.0  # exactly zero, never spuriously positive


def test_c_common_trend_both_arms_up_cancels_to_zero() -> None:
    # market drift: both arms +7 over the window -> DiD removes it.
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=cell(17.0),
        baseline_control=cell(30.0),
        post_control=cell(37.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.treatment_raw_delta == pytest.approx(7.0)
    assert sig.control_raw_delta == pytest.approx(7.0)
    assert sig.net_of_control_lift == pytest.approx(0.0)


def test_d_fraud_parity_treatment_plus5_control_plus5_is_zero() -> None:
    # F-9 / k3s §10:513: "raw citation count grows but control too" -> lift 0.
    s = series(
        baseline_treatment=cell(100.0),
        post_treatment=cell(105.0),  # +5
        baseline_control=cell(100.0),
        post_control=cell(105.0),  # +5
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.treatment_raw_delta == pytest.approx(5.0)
    assert sig.net_of_control_lift == 0.0  # raw grew, but so did control -> no lift


def test_d_fraud_parity_matches_superseded_f9_semantics() -> None:
    """The superseded F-9 evaluator computed
    net = treatment_raw_delta - control_raw_delta. Our engine must produce
    the identical scalar on the same raw deltas (ADOPT the semantic, add
    decomposition + insufficiency on top)."""
    s = series(
        baseline_treatment=cell(100.0),
        post_treatment=cell(105.0),
        baseline_control=cell(100.0),
        post_control=cell(105.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    f9_net = sig.treatment_raw_delta - sig.control_raw_delta
    assert sig.net_of_control_lift == f9_net == 0.0


def test_e_negative_lift_reported_negative() -> None:
    # treatment +1, control +5 -> net -4 (treatment did WORSE than drift).
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=cell(11.0),
        baseline_control=cell(10.0),
        post_control=cell(15.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.net_of_control_lift == pytest.approx(-4.0)
    assert sig.net_of_control_lift < 0.0


# --------------------------------------------------------------------------
# Insufficiency (f), (g) and missing-cell codes — NEVER guess
# --------------------------------------------------------------------------


def test_f_tiny_n_is_insufficient_not_a_verdict() -> None:
    # 2 repeats < policy.min_repeats(3) -> insufficient_repeats, lift not asserted.
    s = series(
        baseline_treatment=cell(10.0, repeats=2),
        post_treatment=cell(20.0, repeats=2),
        baseline_control=cell(10.0, repeats=2),
        post_control=cell(12.0, repeats=2),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.insufficient
    assert InsufficiencyCode.INSUFFICIENT_REPEATS in sig.insufficiency_codes
    # numbers still reported for transparency, but marked insufficient
    assert sig.net_of_control_lift is not None


def test_g_missing_baseline_is_insufficient_missing_baseline() -> None:
    s = series(
        baseline_treatment=None,
        post_treatment=cell(20.0),
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.insufficient
    assert InsufficiencyCode.MISSING_BASELINE in sig.insufficiency_codes


def test_g_missing_control_is_insufficient_missing_control() -> None:
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=cell(20.0),
        baseline_control=None,
        post_control=None,
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.insufficient
    assert InsufficiencyCode.MISSING_CONTROL in sig.insufficiency_codes


def test_g_nan_cell_value_is_insufficient_never_silent_drop() -> None:
    # A NaN repeat value must surface as insufficient, not be silently dropped
    # or produce a NaN lift that some downstream >0 check treats as "positive".
    s = series(
        baseline_treatment=cell(float("nan")),
        post_treatment=cell(20.0),
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.insufficient
    assert InsufficiencyCode.NON_FINITE_VALUE in sig.insufficiency_codes
    # lift must never be a silent NaN masquerading as a real number
    if sig.net_of_control_lift is not None:
        assert not math.isnan(sig.net_of_control_lift)


def test_g_inf_cell_value_is_insufficient() -> None:
    s = series(
        baseline_treatment=cell(float("inf")),
        post_treatment=cell(20.0),
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.insufficient
    assert InsufficiencyCode.NON_FINITE_VALUE in sig.insufficiency_codes


def test_missing_both_baseline_and_control_reports_both_codes() -> None:
    s = series(
        baseline_treatment=None,
        post_treatment=cell(20.0),
        baseline_control=None,
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    codes = set(sig.insufficiency_codes)
    assert InsufficiencyCode.MISSING_BASELINE in codes
    assert InsufficiencyCode.MISSING_CONTROL in codes


def test_missing_post_treatment_is_insufficient() -> None:
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=None,
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.insufficient
    assert InsufficiencyCode.MISSING_POST in sig.insufficiency_codes


# --------------------------------------------------------------------------
# Late observation: excluded + flagged, not silently averaged in
# --------------------------------------------------------------------------


def test_late_observation_excluded_from_cell_and_flagged_late() -> None:
    from saena_domain.measurement.did import CellObservation

    # 3 in-window repeats (all 20.0) + 1 late repeat (999.0). The late one must
    # be excluded from the mean (mean stays 20.0) and flagged.
    from .conftest import IN_WINDOW

    treated_post = CellObservation(
        repeat_values=(20.0, 20.0, 20.0, 999.0),
        timestamps=(IN_WINDOW, IN_WINDOW, IN_WINDOW, LATE),
    )
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=treated_post,
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY, window_start=WINDOW_START, window_end=WINDOW_END).signals[0]
    assert sig.late_observation
    # late 999.0 excluded -> mean 20.0 -> treatment delta 10.0, net 8.0
    assert sig.treatment_raw_delta == pytest.approx(10.0)
    assert sig.net_of_control_lift == pytest.approx(8.0)
    # excluded count reported, not hidden
    assert sig.excluded_late_count >= 1


def test_all_repeats_late_makes_cell_insufficient_repeats() -> None:
    from saena_domain.measurement.did import CellObservation

    late_only = CellObservation(
        repeat_values=(20.0, 20.0, 20.0),
        timestamps=(LATE, LATE, LATE),
    )
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=late_only,
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY, window_start=WINDOW_START, window_end=WINDOW_END).signals[0]
    assert sig.insufficient
    assert sig.late_observation
    assert InsufficiencyCode.INSUFFICIENT_REPEATS in sig.insufficiency_codes


# --------------------------------------------------------------------------
# Unequal repeats: explicit mean-per-repeat normalization + sample counts
# --------------------------------------------------------------------------


def test_unequal_repeats_normalized_by_mean_with_sample_counts() -> None:
    from saena_domain.measurement.did import CellObservation

    # treatment post has 4 repeats averaging 20.0; other cells 3 repeats.
    from .conftest import IN_WINDOW

    post_t = CellObservation(
        repeat_values=(18.0, 20.0, 20.0, 22.0),  # mean 20.0
        timestamps=(IN_WINDOW,) * 4,
    )
    s = series(
        baseline_treatment=cell(10.0, repeats=3),
        post_treatment=post_t,
        baseline_control=cell(10.0, repeats=3),
        post_control=cell(12.0, repeats=3),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.net_of_control_lift == pytest.approx(8.0)
    # sample counts reported per cell
    assert sig.sample_counts["post_treatment"] == 4
    assert sig.sample_counts["baseline_treatment"] == 3


def test_mean_normalization_is_exact_for_repeating_fraction() -> None:
    from saena_domain.measurement.did import CellObservation

    from .conftest import IN_WINDOW

    # mean of (1,1,1) over 3 = exactly 1; use a cell whose mean is 1/3-ish to
    # verify exact-fraction handling: (0,0,1) mean = 1/3.
    post_t = CellObservation(repeat_values=(0.0, 0.0, 1.0), timestamps=(IN_WINDOW,) * 3)
    s = series(
        baseline_treatment=cell(0.0),
        post_treatment=post_t,
        baseline_control=cell(0.0),
        post_control=cell(0.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    # 1/3 with the engine's rounding policy
    assert sig.net_of_control_lift == pytest.approx(1.0 / 3.0, abs=1e-9)


# --------------------------------------------------------------------------
# Raw AND control-adjusted views both exposed
# --------------------------------------------------------------------------


def test_both_raw_and_control_adjusted_views_present() -> None:
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=cell(20.0),
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    # raw view: treatment post-baseline delta, ignoring control
    assert sig.raw_view.treatment_delta == pytest.approx(10.0)
    assert sig.raw_view.control_delta == pytest.approx(2.0)
    # control-adjusted view: the DiD scalar
    assert sig.adjusted_view.net_of_control_lift == pytest.approx(8.0)


# --------------------------------------------------------------------------
# Determinism + permutation invariance
# --------------------------------------------------------------------------


def _two_signals() -> tuple:
    s1 = series(
        metric_id="citation_count",
        layer="citation",
        evidence_basis_id="eb-1",
        baseline_treatment=cell(10.0),
        post_treatment=cell(20.0),
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    s2 = series(
        metric_id="ctr",
        layer="click",
        evidence_basis_id="eb-2",
        baseline_treatment=cell(1.0),
        post_treatment=cell(3.0),
        baseline_control=cell(1.0),
        post_control=cell(1.0),
    )
    return s1, s2


def test_determinism_byte_identical_canonical_output() -> None:
    s1, s2 = _two_signals()
    a = compute_did((s1, s2), POLICY).canonical_json()
    b = compute_did((s1, s2), POLICY).canonical_json()
    assert a == b


def test_result_independent_of_input_ordering() -> None:
    s1, s2 = _two_signals()
    forward = compute_did((s1, s2), POLICY).canonical_json()
    reversed_ = compute_did((s2, s1), POLICY).canonical_json()
    # canonical output is keyed/sorted by signal identity, so order cannot matter
    assert forward == reversed_


def test_three_runs_identical() -> None:
    s1, s2 = _two_signals()
    outs = {compute_did((s1, s2), POLICY).canonical_json() for _ in range(3)}
    assert len(outs) == 1


# --------------------------------------------------------------------------
# Uncertainty: leave-one-out sign stability + min detectable margin
# --------------------------------------------------------------------------


def test_sign_stability_stable_when_all_repeats_agree() -> None:
    from saena_domain.measurement.did import CellObservation

    from .conftest import IN_WINDOW

    # every treatment-post repeat is high; dropping any one keeps net positive.
    post_t = CellObservation(repeat_values=(19.0, 20.0, 21.0), timestamps=(IN_WINDOW,) * 3)
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=post_t,
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.sign_stable_under_leave_one_out is True


def test_sign_instability_when_one_repeat_flips_sign() -> None:
    from saena_domain.measurement.did import CellObservation

    from .conftest import IN_WINDOW

    # net is barely positive; a single influential low repeat flips it negative
    # when left in vs out -> not sign-stable.
    post_t = CellObservation(repeat_values=(2.0, 2.0, 40.0), timestamps=(IN_WINDOW,) * 3)
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=post_t,
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.sign_stable_under_leave_one_out is False


def test_leave_one_out_is_deterministic_no_rng() -> None:
    from saena_domain.measurement.did import CellObservation

    from .conftest import IN_WINDOW

    post_t = CellObservation(repeat_values=(2.0, 2.0, 40.0), timestamps=(IN_WINDOW,) * 3)
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=post_t,
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    a = compute_did((s,), POLICY).signals[0].sign_stable_under_leave_one_out
    b = compute_did((s,), POLICY).signals[0].sign_stable_under_leave_one_out
    assert a == b


def test_min_detectable_margin_vs_effect_threshold() -> None:
    # net lift 8.0, threshold 1.0 -> margin = |8.0| - 1.0 = 7.0 (comfortably above).
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=cell(20.0),
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), make_policy(min_repeats=3, effect_threshold=1.0)).signals[0]
    assert sig.min_detectable_margin == pytest.approx(7.0)
    assert sig.meets_effect_threshold is True


def test_lift_below_threshold_does_not_meet_threshold() -> None:
    # net lift 0.5 < threshold 1.0
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=cell(11.0),  # +1
        baseline_control=cell(10.0),
        post_control=cell(10.5),  # +0.5 -> net 0.5
    )
    sig = compute_did((s,), make_policy(min_repeats=3, effect_threshold=1.0)).signals[0]
    assert sig.net_of_control_lift == pytest.approx(0.5)
    assert sig.meets_effect_threshold is False
    assert sig.min_detectable_margin == pytest.approx(0.5 - 1.0)


# --------------------------------------------------------------------------
# Multi-signal aggregation shape (numbers only; NO B-gate verdict here)
# --------------------------------------------------------------------------


def test_result_reports_per_signal_no_verdict_field() -> None:
    s1, s2 = _two_signals()
    r = compute_did((s1, s2), POLICY)
    assert len(r.signals) == 2
    # w5-05 reports numbers + insufficiency ONLY; B-gate verdict is w5-06.
    payload = r.canonical_json()
    for banned in ("verdict", "granted", "b_layer", "passed", "pass"):
        assert banned not in payload.lower()


def test_signals_keyed_by_identity_in_output() -> None:
    s1, s2 = _two_signals()
    r = compute_did((s1, s2), POLICY)
    ids = {(sig.layer, sig.metric_id, sig.evidence_basis_id) for sig in r.signals}
    assert ("citation", "citation_count", "eb-1") in ids
    assert ("click", "ctr", "eb-2") in ids


def test_empty_signal_tuple_yields_empty_result() -> None:
    r = compute_did((), POLICY)
    assert r.signals == ()
    assert r.canonical_json()  # still serializes deterministically


# --------------------------------------------------------------------------
# Model / edge-case guards
# --------------------------------------------------------------------------


def test_cell_rejects_mismatched_value_timestamp_lengths() -> None:
    from saena_domain.measurement.did import CellObservation

    from .conftest import IN_WINDOW

    with pytest.raises(ValueError, match="equal length"):
        CellObservation(repeat_values=(1.0, 2.0), timestamps=(IN_WINDOW,))


def test_observation_before_window_start_excluded_and_flagged() -> None:
    from saena_domain.measurement.did import CellObservation

    from .conftest import IN_WINDOW

    early = datetime(2026, 6, 20, 0, 0, 0, tzinfo=WINDOW_START.tzinfo)
    post_t = CellObservation(
        repeat_values=(20.0, 20.0, 20.0, -50.0),  # last one is BEFORE the window
        timestamps=(IN_WINDOW, IN_WINDOW, IN_WINDOW, early),
    )
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=post_t,
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY, window_start=WINDOW_START, window_end=WINDOW_END).signals[0]
    assert sig.late_observation
    assert sig.excluded_late_count >= 1
    # the pre-window -50.0 is excluded -> mean stays 20.0 -> net 8.0
    assert sig.net_of_control_lift == pytest.approx(8.0)


def test_single_repeat_cell_is_sufficient_and_loo_skips_that_cell() -> None:
    # min_repeats=1 makes a 1-repeat cell sufficient; LOO must skip cells it
    # cannot reduce (dropping the only value is undefined) yet still evaluate
    # the reducible cells.
    from saena_domain.measurement.did import CellObservation

    from .conftest import IN_WINDOW

    one_repeat_baseline = CellObservation(repeat_values=(10.0,), timestamps=(IN_WINDOW,))
    multi_post = CellObservation(repeat_values=(19.0, 20.0, 21.0), timestamps=(IN_WINDOW,) * 3)
    s = series(
        baseline_treatment=one_repeat_baseline,
        post_treatment=multi_post,
        baseline_control=cell(10.0, repeats=1),
        post_control=cell(12.0, repeats=1),
    )
    sig = compute_did((s,), make_policy(min_repeats=1, effect_threshold=1.0)).signals[0]
    assert not sig.insufficient
    assert sig.sample_counts["baseline_treatment"] == 1
    # net still positive and stable (post repeats all well above baseline)
    assert sig.net_of_control_lift == pytest.approx(8.0)
    assert sig.sign_stable_under_leave_one_out is True


# --------------------------------------------------------------------------
# Critic #2 should-fix 1: extreme magnitude is per-signal insufficiency,
# never a batch abort
# --------------------------------------------------------------------------


def test_extreme_magnitude_is_per_signal_insufficiency_not_exception() -> None:
    s = series(
        baseline_treatment=cell(1e19),  # >= MAGNITUDE_LIMIT
        post_treatment=cell(20.0),
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]  # must not raise
    assert sig.insufficient
    assert InsufficiencyCode.NON_REPRESENTABLE_MAGNITUDE in sig.insufficiency_codes


def test_absurd_signal_does_not_abort_batch_normal_signal_still_computed() -> None:
    absurd = series(
        metric_id="absurd_metric",
        evidence_basis_id="eb-absurd",
        baseline_treatment=cell(-1e300),
        post_treatment=cell(1e300),
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    normal = series(
        metric_id="citation_count",
        evidence_basis_id="eb-normal",
        baseline_treatment=cell(10.0),
        post_treatment=cell(20.0),
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    r = compute_did((absurd, normal), POLICY)
    by_metric = {sig.metric_id: sig for sig in r.signals}
    assert by_metric["absurd_metric"].insufficient
    assert (
        InsufficiencyCode.NON_REPRESENTABLE_MAGNITUDE
        in by_metric["absurd_metric"].insufficiency_codes
    )
    # the normal signal is unaffected and exact
    assert not by_metric["citation_count"].insufficient
    assert by_metric["citation_count"].net_of_control_lift == pytest.approx(8.0)
    # and the batch output still canonicalizes
    assert r.canonical_json()


def test_magnitude_just_below_limit_is_computable() -> None:
    from saena_domain.measurement.did import MAGNITUDE_LIMIT

    v = MAGNITUDE_LIMIT / 1e6  # comfortably representable
    s = series(
        baseline_treatment=cell(v),
        post_treatment=cell(v),
        baseline_control=cell(0.0),
        post_control=cell(0.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert not sig.insufficient
    assert sig.net_of_control_lift == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Critic #2 should-fix 2: observation identity / replay dedup
# --------------------------------------------------------------------------


def test_replayed_identical_observation_ids_deduped_and_cannot_satisfy_min_repeats() -> None:
    from saena_domain.measurement.did import CellObservation

    from .conftest import IN_WINDOW

    # 3 physical repeats but all the SAME observation replayed -> 1 unique
    # -> below min_repeats(3) -> insufficient, replay cannot inflate counts.
    replayed = CellObservation(
        repeat_values=(20.0, 20.0, 20.0),
        timestamps=(IN_WINDOW,) * 3,
        observation_ids=("obs-1", "obs-1", "obs-1"),
    )
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=replayed,
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.sample_counts["post_treatment"] == 1  # deduped
    assert sig.insufficient
    assert InsufficiencyCode.INSUFFICIENT_REPEATS in sig.insufficiency_codes


def test_distinct_observation_ids_counted_normally() -> None:
    from saena_domain.measurement.did import CellObservation

    from .conftest import IN_WINDOW

    distinct = CellObservation(
        repeat_values=(19.0, 20.0, 21.0),
        timestamps=(IN_WINDOW,) * 3,
        observation_ids=("obs-1", "obs-2", "obs-3"),
    )
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=distinct,
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert not sig.insufficient
    assert sig.sample_counts["post_treatment"] == 3
    assert sig.net_of_control_lift == pytest.approx(8.0)


def test_same_observation_id_different_value_is_duplicate_conflict() -> None:
    from saena_domain.measurement.did import CellObservation

    from .conftest import IN_WINDOW

    conflicting = CellObservation(
        repeat_values=(20.0, 25.0, 21.0),  # obs-1 appears twice with different values
        timestamps=(IN_WINDOW,) * 3,
        observation_ids=("obs-1", "obs-1", "obs-2"),
    )
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=conflicting,
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert sig.insufficient
    assert InsufficiencyCode.DUPLICATE_OBSERVATION_CONFLICT in sig.insufficiency_codes


def test_without_observation_ids_no_dedup_upstream_obligation() -> None:
    # ids absent -> engine performs NO dedup (documented upstream obligation of
    # w5-04 binding / w5-12 service). Identical repeats count individually.
    s = series(
        baseline_treatment=cell(10.0),
        post_treatment=cell(20.0),  # 3 identical repeats, no ids
        baseline_control=cell(10.0),
        post_control=cell(12.0),
    )
    sig = compute_did((s,), POLICY).signals[0]
    assert not sig.insufficient
    assert sig.sample_counts["post_treatment"] == 3


def test_observation_ids_length_mismatch_rejected() -> None:
    from saena_domain.measurement.did import CellObservation

    from .conftest import IN_WINDOW

    with pytest.raises(ValueError, match="observation_ids"):
        CellObservation(
            repeat_values=(1.0, 2.0),
            timestamps=(IN_WINDOW, IN_WINDOW),
            observation_ids=("obs-1",),
        )


# --------------------------------------------------------------------------
# Critic #2 should-fix 3: closed provenance vocabulary
# --------------------------------------------------------------------------


def test_policy_provenance_accepts_only_closed_vocabulary() -> None:
    from pydantic import ValidationError
    from saena_domain.measurement.did import DiDPolicy

    # both closed values construct fine
    DiDPolicy(min_repeats=3, effect_threshold=1.0, provenance="test_fixture")
    DiDPolicy(min_repeats=3, effect_threshold=1.0, provenance="production")

    for bad in ("PRODUCTION", "production ", " test_fixture", "prod", "test-only-fixture", ""):
        with pytest.raises(ValidationError):
            DiDPolicy(min_repeats=3, effect_threshold=1.0, provenance=bad)  # type: ignore[arg-type]

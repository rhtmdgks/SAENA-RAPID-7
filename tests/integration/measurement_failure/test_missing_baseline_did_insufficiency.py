"""Missing baseline/control -> DiD insufficiency (w5-20 deliverable 2, closing
the coverage-matrix gap `test_failure_mode_coverage_matrix.py` names in its own
`_MATRIX` docstring: no EXISTING pipeline-level `run_measurement` unit test
independently exercises a *baseline-only* absence in isolation from
`missing_control`, because `make_happy_path_inputs`'s fixture shape always
supplies BOTH arms, and the sibling `test_missing_control_cell_is_undetermined`
(`tests/unit/svc_experiment_attribution_pipeline/test_did_and_b_gate.py`)
already covers the control-absent half of this pair).

Adversarial coverage checklist item: "missing baseline/control/repeats".

Proves, against the REAL `saena_domain.measurement.did` engine AND the REAL
integrated pipeline (`run_measurement`) over Postgres-backed ports, that an
absent baseline_treatment cell is NEVER silently treated as "no movement"
(a silent lift of 0.0 that could accidentally satisfy a
`net_of_control_lift > 0` gate by construction, or worse, get reported as a
control-adjusted zero-effect PASS) — it is an honest, explicit
INSUFFICIENT/UNDETERMINED result at both the DiD-scalar level and the
pipeline-outcome level, carrying `InsufficiencyCode.MISSING_BASELINE` /
`ReasonCode.MISSING_BASELINE` respectively.

Two levels, mirroring every sibling module's DiD-level + pipeline-level split
(`test_observation_adapter_drift.py`, `test_f9_fraud_repoint.py`):

1. DiD level (`compute_did`, pure, no I/O): a `SignalSeries` with
   `baseline_treatment=None` (post_treatment/baseline_control/post_control
   all present and otherwise well-formed) computes a `SignalDiD` that is
   `insufficient=True`, carries `InsufficiencyCode.MISSING_BASELINE`, and
   whose `net_of_control_lift` is `None` — never a numeric `0.0` standing in
   for "we don't know".
2. Pipeline level: `run_measurement` fed that same baseline-absent signal
   (mixed in with an otherwise-qualifying second signal, over REAL
   Postgres-backed ports) resolves `UNDETERMINED` with
   `ReasonCode.MISSING_BASELINE` in its reason codes, and its status is
   NEVER `PASS` — proving the DiD-level "unknown, not zero" honesty survives
   all the way through the B-gate and the final-status forcer
   (`orchestrator._final_status`) to the outcome record a caller actually
   sees.
"""

from __future__ import annotations

import dataclasses

import pytest
from measurement_failure_factories import make_pg_ports
from pipeline_factories import make_happy_path_inputs, make_policies
from saena_domain.measurement.did import DiDPolicy, InsufficiencyCode, compute_did
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement

pytestmark = pytest.mark.integration


def test_missing_baseline_did_scalar_is_insufficient_not_a_silent_zero() -> None:
    """DiD-level (pure, no I/O, no Postgres needed): a signal with NO
    baseline_treatment cell computes `insufficient=True` +
    `InsufficiencyCode.MISSING_BASELINE`, and its `net_of_control_lift` is
    `None` — the engine never guesses/defaults a missing baseline to a
    same-as-post value (which would silently manufacture a lift of exactly
    0.0, indistinguishable from a genuine zero-effect measurement)."""
    inputs, _registration = make_happy_path_inputs(num_qualifying_layers=1)
    signal = inputs.signals[0]
    assert signal.baseline_treatment is not None  # sanity: happy-path fixture has one

    baseline_absent_signal = signal.model_copy(update={"baseline_treatment": None})

    result = compute_did(
        (baseline_absent_signal,),
        DiDPolicy(min_repeats=3, effect_threshold=0.5, provenance="test_fixture"),
        window_start=None,
        window_end=None,
    )

    assert len(result.signals) == 1
    signal_did = result.signals[0]
    assert signal_did.insufficient is True
    assert InsufficiencyCode.MISSING_BASELINE in signal_did.insufficiency_codes
    # Never a manufactured numeric answer standing in for "unknown".
    assert signal_did.net_of_control_lift is None
    assert signal_did.treatment_raw_delta is None


def test_missing_baseline_is_insufficient_never_a_silent_zero(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """Pipeline level, over REAL Postgres-backed ports: one signal missing its
    baseline_treatment cell, mixed with one otherwise-qualifying signal, must
    resolve UNDETERMINED with `ReasonCode.MISSING_BASELINE` — never PASS, and
    never a FAIL that silently absorbed the missing-baseline signal as if it
    contributed a real (zero) measurement."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    baseline_absent_signal = inputs.signals[0].model_copy(update={"baseline_treatment": None})
    bad_inputs = dataclasses.replace(inputs, signals=(baseline_absent_signal, *inputs.signals[1:]))
    policies = make_policies(registration)
    ports = make_pg_ports(postgres_url)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.MISSING_BASELINE in outcome.reason_codes
    assert outcome.status is not OutcomeStatus.PASS

    # Re-evaluating the SAME insufficient inputs again (idempotent replay)
    # must not "get lucky" and upgrade to a decision on a second try — the
    # honest gap is stable, not eventually resolved by retrying.
    outcome_again = run_measurement(bad_inputs, ports, policies)
    assert outcome_again.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.MISSING_BASELINE in outcome_again.reason_codes
    assert outcome_again.canonical_payload() == outcome.canonical_payload()


def test_missing_baseline_all_signals_is_undetermined_not_a_crash(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """Total baseline absence (every signal missing baseline_treatment) must
    still resolve to an honest UNDETERMINED outcome record — fail-closed, not
    fail-crash — mirroring the sibling adapter-drift "all signals drifted"
    proof."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    fully_baseline_absent_signals = tuple(
        s.model_copy(update={"baseline_treatment": None}) for s in inputs.signals
    )
    bad_inputs = dataclasses.replace(inputs, signals=fully_baseline_absent_signals)
    policies = make_policies(registration)
    ports = make_pg_ports(postgres_url)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.MISSING_BASELINE in outcome.reason_codes
    assert outcome.status is not OutcomeStatus.PASS

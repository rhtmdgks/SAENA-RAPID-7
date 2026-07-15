"""Cross-module adversarial composition suite for the Wave-5 measurement plane
(w5-18) — the seams FIT and stay fail-closed under composition.

Exit-matrix conditions exercised here (wave5-plan.md §Exit matrix):
- **E5** — evidence bundle tamper-evidence composes into the B-gate
  (`verify_manifest(False)` -> `EvidenceCheck(manifest_hash_ok=False)` ->
  `UNDETERMINED(evidence_hash_mismatch)`).
- **E8** — cross-module fail-closed composition + UNDETERMINED-never-PASS.
- **E12** — "No forbidden P1/Future activation; no deploy; no unsupported lift
  claim": the whole point of these tests is that a degraded / fraudulent /
  policy-missing input can NEVER compose into a production PASS.

## What this suite proves (integration-shaped, pure Python)

The per-unit suites prove each module's OWN fail-closed behaviour. This suite
proves the COMPOSITION: that one module's fail-closed output is the exact input
the next module fails closed on, so a gap can't open BETWEEN two individually
correct modules. Concretely:

1. Unverified confirmation -> the clock never starts -> the B-gate's
   `deployment_unconfirmed` UNDETERMINED path composes (the reason propagates).
2. A tampered evidence manifest -> `verify_manifest(False)` -> the B-gate's
   `evidence_hash_mismatch` UNDETERMINED path composes.
3. A missing GRS bundle -> `grs_policy_missing` UNDETERMINED, and the B-gate
   decision provenance the pipeline would carry stays NON-production.
4. The full k3s §10:513 fraud scenario end to end: registration -> confirmation
   -> window -> raw-up-BOTH-arms observations -> DiD zero-lift -> B-gate
   FAIL/UNDETERMINED, evidence-bundle completeness honestly reported. ONE
   composed test proving the seams fit.
5. A property-style sweep over the degraded-input space: the B-gate verdict is
   NEVER `pass`, and reason codes are always non-empty, on any degraded input.

This suite is read-only against every unit module and never touches
`measurement_fraud.py` (the superseded F-9 evaluator).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from saena_domain.experiment.ledger import register
from saena_domain.experiment.models import (
    ExperimentArm,
    ExperimentRegistration,
    MetricDefinition,
)
from saena_domain.measurement.b_gate import (
    BGateDecision,
    BVerdict,
    EvidenceCheck,
    GatePolicy,
    PolicyProvenance,
    SignalResult,
    WindowState,
    decide_b_verdict,
)
from saena_domain.measurement.binding import (
    MeasurementCell,
    MeasurementMetricInput,
    MeasurementSubmission,
    Observation,
    WeightsPolicy,
    bind_experiment,
    compute_metric_fingerprint,
)
from saena_domain.measurement.clock import (
    Undetermined as ClockUndetermined,
)
from saena_domain.measurement.clock import (
    start_measurement_window,
)
from saena_domain.measurement.confirmation import (
    Accepted,
    DeploymentConfirmation,
    RegistrationView,
    Rejected,
    RejectionReason,
    validate_confirmation,
)
from saena_domain.measurement.did import (
    CellObservation,
    DiDPolicy,
    SignalSeries,
    compute_did,
)
from saena_domain.measurement.evidence import (
    EvidenceBundleManifest,
    EvidenceEntry,
    EvidenceKind,
    EvidenceRef,
    validate_completeness,
    verify_manifest,
)
from saena_domain.measurement.grs import (
    GrsEligibility,
    evaluate_grs_eligibility,
    make_test_fixture_policy,
)
from saena_domain.measurement.outcome_layer import OutcomeLayer
from saena_domain.measurement.reason_codes import ReasonCode

TENANT_A = "acme-co"
_CREATED = datetime(2026, 7, 14, 8, 0, 0, tzinfo=UTC)
_SERVER_RECEIVED = _CREATED + timedelta(hours=1)
_SHA_A = "sha256:" + "a" * 64
_SHA_1 = "sha256:" + "1" * 64
_SHA_2 = "sha256:" + "2" * 64

#: Test-fixture gate policy — provenance test_fixture, so every decision built
#: with it is `is_production=False`. A production-labelled policy is never
#: constructed in this suite (mechanism-only; production BLOCKED(human)).
_FIXTURE_POLICY = GatePolicy(version="0.0.0", hash=_SHA_A, provenance=PolicyProvenance.TEST_FIXTURE)


class _NoVerifier:
    """A verifier that REFUSES — the unverified-confirmer adversary."""

    def verify(self, confirmation: DeploymentConfirmation) -> bool:
        return False


# --------------------------------------------------------------------------
# Chain builders
# --------------------------------------------------------------------------


def _registration() -> ExperimentRegistration:
    reg = ExperimentRegistration(
        experiment_id="exp-1",
        tenant_id=TENANT_A,
        run_id="run-1",
        arms=(
            ExperimentArm(arm_id="b", role="baseline"),
            ExperimentArm(arm_id="t", role="treatment", asset_ref="asset-t"),
            ExperimentArm(arm_id="c", role="control", asset_ref="asset-c"),
        ),
        metric_definitions=(
            MetricDefinition(metric_id="m1", description="citations"),
            MetricDefinition(metric_id="m2", description="prominence"),
        ),
        query_cluster_ref="qc-1",
        locale="en-US",
        browser_policy="default",
        repeat_count=3,
        asset_hash=_SHA_1,
        code_version_hash=_SHA_2,
        created_by="alice",
        approved_by="bob",
        created_at=_CREATED,
    )
    _ledger, stored = register((), reg)
    return stored


def _view(reg: ExperimentRegistration) -> RegistrationView:
    return RegistrationView(
        experiment_id=reg.experiment_id,
        tenant_id=reg.tenant_id,
        run_id=reg.run_id,
        project="proj",
        site="site",
        registration_canonical_hash=reg.canonical_hash,
        created_at=_CREATED,
        approved_at=_CREATED,
    )


def _confirmation(reg: ExperimentRegistration) -> DeploymentConfirmation:
    return DeploymentConfirmation(
        experiment_id=reg.experiment_id,
        tenant_id=reg.tenant_id,
        run_id=reg.run_id,
        project="proj",
        site="site",
        registration_canonical_hash=reg.canonical_hash,
        deployment_target="prod",
        deployed_commit_sha="abc123def",
        confirmed_at=_SERVER_RECEIVED,
        idempotency_key="idem-1",
        confirmer_identity="deployer",
        confirmer_signature="signature-bytes",
    )


class _AcceptVerifier:
    def verify(self, confirmation: DeploymentConfirmation) -> bool:
        return True


#: An observation instant safely INSIDE the measurement window (anchored at
#: `_SERVER_RECEIVED`, ending 7 days later) — so DiD does not exclude the
#: fraud observations as late/out-of-window.
_IN_WINDOW = _SERVER_RECEIVED + timedelta(days=1)


def _did_cell(value: float) -> CellObservation:
    return CellObservation(repeat_values=(value, value, value), timestamps=(_IN_WINDOW,) * 3)


# ==========================================================================
# TEST 3 — Cross-module fail-closed COMPOSITION (E5/E8/E12)
# ==========================================================================


def test_3a_unverified_confirmation_clock_never_starts_bgate_undetermined_composes() -> None:
    """E8: (a) an unverified confirmation is Rejected -> `start_measurement_window`
    is structurally unreachable (it takes ONLY an Accepted) -> the B-gate's
    `deployment_unconfirmed` UNDETERMINED path composes.

    Proves the seam FIT: the confirmation module's fail-closed output (a
    Rejected, not an Accepted) is exactly what makes the downstream window
    absent, which is exactly the `deployment_confirmed=False` the B-gate turns
    into UNDETERMINED(deployment_unconfirmed).
    """
    reg = _registration()
    view = _view(reg)

    verdict = validate_confirmation(_confirmation(reg), view, _SERVER_RECEIVED, _NoVerifier(), {})
    assert isinstance(verdict, Rejected)
    assert verdict.reason_code is RejectionReason.CONFIRMER_VERIFICATION_FAILED
    assert not isinstance(verdict, Accepted)

    # No Accepted -> no window ever starts. The B-gate is fed the state that
    # absence composes into: deployment_confirmed=False.
    decision = decide_b_verdict(
        (),
        EvidenceCheck(manifest_hash_ok=True, raw_refs_present=True),
        WindowState(complete=True, deployment_confirmed=False),
        _FIXTURE_POLICY,
    )
    assert decision.verdict is BVerdict.UNDETERMINED
    assert ReasonCode.DEPLOYMENT_UNCONFIRMED in decision.reason_codes
    assert decision.is_production is False


def test_3b_evidence_hash_mismatch_composes_with_verify_manifest_false() -> None:
    """E5/E8: (b) a tampered evidence manifest -> `verify_manifest` returns
    `(False, ...)` -> that False is the `EvidenceCheck.manifest_hash_ok=False`
    the B-gate turns into UNDETERMINED(evidence_hash_mismatch).

    Proves the w5-08 -> w5-06 seam: the evidence module's tamper detector's
    boolean output is the exact B-gate input, so a spliced/tampered bundle can
    never silently compose into a PASS.
    """
    entry = EvidenceEntry(
        kind=EvidenceKind.B_GATE_DECISION,
        ref=EvidenceRef(uri="artifact://decision", content_hash=_SHA_A),
    )
    sealed = EvidenceBundleManifest.seal(
        tenant_id=TENANT_A, run_id="run-1", experiment_id="exp-1", entries=(entry,)
    )
    # Force-tamper the sealed head (model_copy bypasses re-validation), the
    # w5-08 docstring's "force-mutated object" case that only verify_manifest
    # catches.
    tampered = sealed.model_copy(update={"manifest_hash": "sha256:" + "f" * 64})

    ok, _index = verify_manifest(tampered)
    assert ok is False  # w5-08 detects it

    # Compose w5-08's boolean into the B-gate's EvidenceCheck.
    decision = decide_b_verdict(
        (),
        EvidenceCheck(manifest_hash_ok=ok, raw_refs_present=True),
        WindowState(complete=True, deployment_confirmed=True),
        _FIXTURE_POLICY,
    )
    assert decision.verdict is BVerdict.UNDETERMINED
    assert ReasonCode.EVIDENCE_HASH_MISMATCH in decision.reason_codes
    assert decision.is_production is False


def test_3c_grs_bundle_missing_undetermined_and_bgate_provenance_non_production() -> None:
    """E8/E12: (c) a missing GRS bundle -> `evaluate_grs_eligibility` returns
    UNDETERMINED(grs_policy_missing) with `is_production_valid=False`, AND a
    B-gate decision built against a test-fixture policy stays non-production.

    Proves that neither the GRS seam nor the B-gate seam can mint a production
    guarantee when the signed policy bundle is absent — both report
    non-production, composing honestly (mechanism PASS / production BLOCKED).
    """
    grs = evaluate_grs_eligibility(
        {"grs": 0.99, "independent_layers": 5, "open_incidents": 0}, bundle=None
    )
    assert grs.decision is GrsEligibility.UNDETERMINED
    assert grs.reason == "grs_policy_missing"
    assert grs.is_production_valid is False

    # Even a fixture bundle that WOULD evaluate never reports production-valid.
    fixture_bundle = make_test_fixture_policy(
        {"min_grs": 0.0, "min_independent_layers": 0, "max_open_incidents": 99}
    )
    fixture_decision = evaluate_grs_eligibility(
        {"grs": 0.99, "independent_layers": 5, "open_incidents": 0}, bundle=fixture_bundle
    )
    assert fixture_decision.is_production_valid is False

    # The B-gate decision provenance the pipeline carries stays non-production.
    decision = decide_b_verdict(
        (),
        EvidenceCheck(manifest_hash_ok=True, raw_refs_present=True),
        WindowState(complete=True, deployment_confirmed=True),
        _FIXTURE_POLICY,
    )
    assert decision.is_production is False
    assert decision.policy_provenance is PolicyProvenance.TEST_FIXTURE


# ==========================================================================
# TEST 4 — Full-chain fraud scenario (k3s §10:513) — one composed test (E8/E12)
# ==========================================================================


def test_4_full_chain_fraud_scenario_raw_up_both_arms_never_passes() -> None:
    """E8/E12 (k3s §10:513): registration -> confirmation -> window ->
    raw-up-in-BOTH-arms observations -> DiD zero-lift -> B-gate FAIL, evidence
    completeness honest. ONE composed test proving the seams fit end to end.

    The fraud: the treatment arm's raw count really grew (raw_view shows it),
    but the control arm grew by the SAME amount over the same window, so the
    net-of-control lift is exactly 0 — market drift, not a real effect. Every
    seam must let the raw movement through to the raw view yet refuse to mint a
    B-layer PASS.
    """
    # --- registration + confirmation + window (real chain) -----------------
    reg = _registration()
    view = _view(reg)
    accepted = validate_confirmation(
        _confirmation(reg), view, _SERVER_RECEIVED, _AcceptVerifier(), {}
    )
    assert isinstance(accepted, Accepted)
    window = start_measurement_window(accepted, view)
    assert not isinstance(window, ClockUndetermined)  # a real window started

    # --- binding: the honest submission binds -----------------------------
    cell = MeasurementCell(
        locale=reg.locale,
        browser_policy=reg.browser_policy,
        query_cluster_ref=reg.query_cluster_ref,
        repeat_count=reg.repeat_count,
    )
    submission = MeasurementSubmission(
        experiment_id=reg.experiment_id,
        tenant_id=reg.tenant_id,
        anchored_hash=reg.canonical_hash,
        content_fingerprint=reg.content_fingerprint,
        metrics=(
            MeasurementMetricInput(
                metric_id="m1",
                metric_hash=compute_metric_fingerprint(reg.metric_definitions[0]),
                weight=1.0,
            ),
        ),
        observations=(
            Observation(observation_id="o1", arm_id="t", cell=cell, asset_hash=reg.asset_hash),
        ),
    )
    bound = bind_experiment(reg, submission, weights=WeightsPolicy.not_registered())
    assert bound.experiment_id == "exp-1"

    # --- DiD: raw grows in BOTH arms equally -> net-of-control lift == 0 ----
    fraud_series = SignalSeries(
        layer="citation",
        metric_id="m1",
        evidence_basis_id="e1",
        baseline_treatment=_did_cell(5.0),
        post_treatment=_did_cell(15.0),  # treatment raw +10
        baseline_control=_did_cell(5.0),
        post_control=_did_cell(15.0),  # control raw +10 (market drift)
    )
    did_policy = DiDPolicy(min_repeats=1, effect_threshold=0.0, provenance="test_fixture")
    did = compute_did(
        (fraud_series,), did_policy, window_start=window.anchor, window_end=window.end
    )
    signal = did.signals[0]
    assert signal.treatment_raw_delta == 10.0  # raw movement is real
    assert signal.control_raw_delta == 10.0
    assert signal.net_of_control_lift == 0.0  # ...but net is zero: no effect

    # --- B-gate: DiD numbers -> SignalResult -> verdict is NOT a PASS ------
    gate_signal = SignalResult(
        layer=OutcomeLayer.CITATION,
        evidence_basis_id=signal.evidence_basis_id,
        treatment_raw_delta=signal.treatment_raw_delta,
        control_raw_delta=signal.control_raw_delta,
        net_of_control_lift=signal.net_of_control_lift,
    )
    decision = decide_b_verdict(
        (gate_signal,),
        EvidenceCheck(manifest_hash_ok=True, raw_refs_present=True),
        WindowState(complete=True, deployment_confirmed=True),
        _FIXTURE_POLICY,
    )
    assert decision.verdict is not BVerdict.PASS
    assert decision.verdict is BVerdict.FAIL
    # The contrast the F-9 fixture is about: raw movement is SHOWN, the
    # control-adjusted view is EMPTY, and the reason names the zero lift.
    assert OutcomeLayer.CITATION in decision.raw_view
    assert decision.control_adjusted_view == ()
    assert ReasonCode.NEGATIVE_OR_INCONCLUSIVE_LIFT in decision.reason_codes
    assert decision.is_production is False

    # --- evidence completeness is honest: a B-gate-only bundle is incomplete,
    # and validate_completeness SAYS SO (never silently complete) ----------
    partial_manifest = EvidenceBundleManifest.seal(
        tenant_id=TENANT_A,
        run_id="run-1",
        experiment_id="exp-1",
        entries=(
            EvidenceEntry(
                kind=EvidenceKind.B_GATE_DECISION,
                ref=EvidenceRef(uri="artifact://decision", content_hash=_SHA_A),
            ),
        ),
    )
    is_complete, missing = validate_completeness(partial_manifest)
    assert is_complete is False
    assert EvidenceKind.REGISTRATION in missing  # honestly names its gaps


# ==========================================================================
# TEST 6 — UNDETERMINED-never-PASS meta-test (property-style sweep) (E8/E12)
# ==========================================================================


def _one_qualifying_signal() -> SignalResult:
    """A single genuinely-qualifying signal (positive net lift). On its own it
    is a FAIL(single_layer_only); paired with a degrading window/evidence state
    it must become UNDETERMINED — never PASS."""
    return SignalResult(
        layer=OutcomeLayer.CITATION,
        evidence_basis_id="e1",
        treatment_raw_delta=10.0,
        control_raw_delta=1.0,
        net_of_control_lift=9.0,
    )


def _two_qualifying_signals() -> tuple[SignalResult, ...]:
    """Two independent qualifying layers — the ONLY shape that COULD PASS. The
    sweep pairs even this with each degradation to prove degradation always
    demotes it away from PASS."""
    return (
        SignalResult(
            layer=OutcomeLayer.CITATION,
            evidence_basis_id="e1",
            treatment_raw_delta=10.0,
            control_raw_delta=1.0,
            net_of_control_lift=9.0,
        ),
        SignalResult(
            layer=OutcomeLayer.PROMINENCE,
            evidence_basis_id="e2",
            treatment_raw_delta=8.0,
            control_raw_delta=1.0,
            net_of_control_lift=7.0,
        ),
    )


def test_6_undetermined_never_pass_property_sweep_over_degraded_inputs() -> None:
    """E8/E12: sweep the degraded-input space (missing baseline/control, late /
    incomplete window, contamination, adapter drift, non-finite input,
    deployment unconfirmed/late) crossed with signal populations, and assert
    the verdict is NEVER `pass` and reason codes are ALWAYS non-empty on any
    degraded input.

    A property-style meta-test: it does not assert a single scenario, it
    asserts an INVARIANT over the whole degradation cross-product — the
    directive's "UNDETERMINED-never-PASS" guarantee. The ONE non-degraded
    control case (two qualifying signals, clean window/evidence) is asserted to
    PASS, so the sweep is proven capable of distinguishing a pass from a
    demotion (it is not vacuously never-passing).
    """
    clean_evidence = EvidenceCheck(manifest_hash_ok=True, raw_refs_present=True)

    # Each degradation is a single-field mutation of an OTHERWISE-clean state.
    # Every one of these MUST force UNDETERMINED regardless of the signals.
    window_degradations = {
        "incomplete_window": {"complete": False},
        "deployment_unconfirmed": {"deployment_confirmed": False},
        "deployment_late": {"deployment_late": True},
        "contamination": {"contamination": True},
        "adapter_drift": {"adapter_drift": True},
        "missing_baseline": {"missing_baseline": True},
        "missing_control": {"missing_control": True},
        "insufficient_repeats": {"insufficient_repeats": True},
    }
    evidence_degradations = {
        "manifest_hash_bad": EvidenceCheck(manifest_hash_ok=False, raw_refs_present=True),
        "raw_refs_absent": EvidenceCheck(manifest_hash_ok=True, raw_refs_present=False),
    }

    signal_populations = {
        "empty": (),
        "one_qualifying": (_one_qualifying_signal(),),
        "two_qualifying": _two_qualifying_signals(),
    }

    checked = 0

    # (1) window-state degradations x every signal population.
    for _wname, mutation in window_degradations.items():
        base = {"complete": True, "deployment_confirmed": True}
        base.update(mutation)
        window_state = WindowState(**base)
        for _sname, signals in signal_populations.items():
            decision = decide_b_verdict(signals, clean_evidence, window_state, _FIXTURE_POLICY)
            assert decision.verdict is not BVerdict.PASS
            assert decision.verdict is BVerdict.UNDETERMINED
            assert decision.reason_codes  # never empty
            assert decision.is_production is False
            checked += 1

    # (2) evidence degradations x every signal population (clean window).
    clean_window = WindowState(complete=True, deployment_confirmed=True)
    for _ename, evidence in evidence_degradations.items():
        for _sname, signals in signal_populations.items():
            decision = decide_b_verdict(signals, evidence, clean_window, _FIXTURE_POLICY)
            assert decision.verdict is not BVerdict.PASS
            assert decision.verdict is BVerdict.UNDETERMINED
            assert decision.reason_codes
            checked += 1

    # (3) a NON-FINITE forged numeric input (model_construct bypass) crossed
    # with an otherwise-clean state must fail closed to UNDETERMINED.
    forged = SignalResult.model_construct(
        layer=OutcomeLayer.CITATION,
        evidence_basis_id="e1",
        treatment_raw_delta=float("inf"),
        control_raw_delta=0.0,
        net_of_control_lift=float("nan"),
        has_control_adjusted_lift=True,
        sufficient_data=True,
        has_raw_evidence_ref=True,
    )
    forged_decision = decide_b_verdict((forged,), clean_evidence, clean_window, _FIXTURE_POLICY)
    assert forged_decision.verdict is BVerdict.UNDETERMINED
    assert ReasonCode.NON_FINITE_INPUT in forged_decision.reason_codes
    checked += 1

    # Control: the ONE clean, non-degraded case DOES pass — proving the sweep
    # can tell a pass from a demotion (not vacuously never-passing).
    clean_pass = decide_b_verdict(
        _two_qualifying_signals(), clean_evidence, clean_window, _FIXTURE_POLICY
    )
    assert clean_pass.verdict is BVerdict.PASS
    assert clean_pass.is_production is False  # test-fixture policy -> non-production

    # A degradation cross-product actually ran (guards against a vacuous sweep).
    assert checked == (
        len(window_degradations) * len(signal_populations)
        + len(evidence_degradations) * len(signal_populations)
        + 1
    )


def test_6_reason_codes_non_empty_on_every_non_pass_verdict() -> None:
    """E8: a companion invariant — ANY non-PASS `BGateDecision` this suite can
    produce carries at least one reason code (a FAIL/UNDETERMINED is never
    silent about WHY). Sweeps a handful of representative shapes and pins the
    invariant `verdict != PASS => reason_codes != ()`."""
    clean_evidence = EvidenceCheck(manifest_hash_ok=True, raw_refs_present=True)
    clean_window = WindowState(complete=True, deployment_confirmed=True)

    shapes: list[BGateDecision] = [
        # empty signals, clean state -> FAIL(single_layer_only)
        decide_b_verdict((), clean_evidence, clean_window, _FIXTURE_POLICY),
        # one qualifying -> FAIL(single_layer_only)
        decide_b_verdict(
            (_one_qualifying_signal(),), clean_evidence, clean_window, _FIXTURE_POLICY
        ),
        # zero-lift fraud -> FAIL(negative_or_inconclusive_lift)
        decide_b_verdict(
            (
                SignalResult(
                    layer=OutcomeLayer.CITATION,
                    evidence_basis_id="e1",
                    treatment_raw_delta=10.0,
                    control_raw_delta=10.0,
                    net_of_control_lift=0.0,
                ),
            ),
            clean_evidence,
            clean_window,
            _FIXTURE_POLICY,
        ),
    ]
    for decision in shapes:
        assert decision.verdict is not BVerdict.PASS
        assert decision.reason_codes, f"{decision.verdict} carried no reason code"

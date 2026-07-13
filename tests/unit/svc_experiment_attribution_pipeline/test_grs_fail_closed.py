"""GRS eligibility runs first, honest, and NEVER produces a PASS on its own
(wave5-plan.md directive: "no bundle -> UNDETERMINED(grs_policy_missing)
recorded, pipeline still produces an honest outcome record, never PASS")."""

from __future__ import annotations

from pipeline_factories import make_happy_path_inputs, make_policies, make_ports
from saena_domain.measurement.grs import GrsEligibility
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement


def test_missing_grs_bundle_forces_undetermined_never_pass() -> None:
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    ports = make_ports()
    policies = make_policies(registration, grs_bundle="missing")

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.GRS_POLICY_MISSING in outcome.reason_codes
    assert outcome.grs_decision is not None
    assert outcome.grs_decision.decision is GrsEligibility.UNDETERMINED
    # The pipeline STILL produced an honest record — not a raised exception.
    assert outcome.evidence_bundle_ref is not None


def test_missing_grs_bundle_still_seals_a_bundle_and_stores_a_decision() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration, grs_bundle="missing")

    outcome = run_measurement(inputs, ports, policies)

    stored = ports.decision_store.get(inputs.tenant_id, (inputs.experiment_id, inputs.run_id))
    assert stored.outcome == "undetermined"
    evidence = ports.evidence_store.get(inputs.tenant_id, outcome.evidence_bundle_ref)
    assert evidence is not None


def test_grs_deny_forces_undetermined_even_with_two_qualifying_layers() -> None:
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    ports = make_ports()
    policies = make_policies(registration, grs_bundle="deny")

    outcome = run_measurement(inputs, ports, policies)

    # Two independent layers really did qualify at the B-gate...
    assert set(outcome.qualifying_layers) == {"discovery", "citation"}
    # ...but GRS non-eligibility still keeps the overall record honest.
    assert outcome.status is not OutcomeStatus.PASS
    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert outcome.grs_decision is not None
    assert outcome.grs_decision.decision is GrsEligibility.DENY


def test_grs_eligible_does_not_by_itself_force_pass() -> None:
    """GRS eligibility is necessary-but-not-sufficient: a run with only ONE
    qualifying layer stays FAIL even though GRS itself is ELIGIBLE."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=1)
    ports = make_ports()
    policies = make_policies(registration, grs_bundle="eligible")

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.status is OutcomeStatus.FAIL
    assert ReasonCode.SINGLE_LAYER_ONLY in outcome.reason_codes

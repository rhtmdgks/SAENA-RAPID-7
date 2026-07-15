"""Full happy path: 2 qualifying independent layers -> PASS + complete bundle."""

from __future__ import annotations

from pipeline_factories import make_happy_path_inputs, make_policies, make_ports
from saena_domain.measurement.b_gate import BVerdict
from saena_domain.measurement.evidence import validate_completeness
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement


def test_happy_path_two_layers_passes() -> None:
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.status is OutcomeStatus.PASS
    assert outcome.reason_codes == ()
    assert set(outcome.qualifying_layers) == {"discovery", "citation"}
    assert outcome.b_gate_decision is not None
    assert outcome.b_gate_decision.verdict is BVerdict.PASS


def test_happy_path_bundle_is_sealed_and_complete() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.evidence_bundle_complete is True
    assert outcome.evidence_bundle_ref is not None

    stored = ports.evidence_store.get(inputs.tenant_id, outcome.evidence_bundle_ref)
    from saena_domain.measurement.evidence import EvidenceBundleManifest, verify_manifest

    manifest = EvidenceBundleManifest(**dict(stored.manifest))
    ok, divergence = verify_manifest(manifest)
    assert ok is True
    assert divergence is None

    is_complete, missing = validate_completeness(manifest)
    assert is_complete is True
    assert missing == frozenset()


def test_happy_path_stores_outcome_decision() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(inputs, ports, policies)

    stored = ports.decision_store.get(inputs.tenant_id, (inputs.experiment_id, inputs.run_id))
    assert stored.outcome == outcome.status.value
    assert stored.evidence_bundle_ref == outcome.evidence_bundle_ref


def test_happy_path_grs_eligible_recorded() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration, grs_bundle="eligible")

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.grs_decision is not None
    from saena_domain.measurement.grs import GrsEligibility

    assert outcome.grs_decision.decision is GrsEligibility.ELIGIBLE

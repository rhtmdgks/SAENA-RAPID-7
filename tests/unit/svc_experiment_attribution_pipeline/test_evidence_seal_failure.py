"""E5: evidence-bundle seal is asserted round-trip (`verify_manifest`)
immediately after sealing — a bundle that does not verify is a
`PipelineError` (genuine integrity violation), never a silently-accepted
outcome. Also: bundle completeness matches verdict honesty (PASS requires a
COMPLETE bundle; UNDETERMINED carries a missingness_report)."""

from __future__ import annotations

import pytest
from pipeline_factories import make_happy_path_inputs, make_policies, make_ports
from saena_domain.measurement.evidence import EvidenceBundleManifest, EvidenceKind
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement
from saena_experiment_attribution.pipeline import orchestrator as orch
from saena_experiment_attribution.pipeline.errors import PipelineError


def test_seal_round_trip_failure_raises_pipeline_error_not_a_verdict(monkeypatch) -> None:
    """Guard-mutation style: force `verify_manifest` to report a divergence
    and confirm the orchestrator refuses to proceed silently."""
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration)

    monkeypatch.setattr(orch.evidence_mod, "verify_manifest", lambda manifest: (False, 0))

    with pytest.raises(PipelineError):
        run_measurement(inputs, ports, policies)

    # No decision was stored — a failed integrity check must not leave a
    # spurious/partial outcome record behind.
    assert ports.decision_store.list_decisions(inputs.tenant_id) == ()


def test_pass_requires_a_complete_bundle() -> None:
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(inputs, ports, policies)

    assert outcome.status is OutcomeStatus.PASS
    assert outcome.evidence_bundle_complete is True

    stored = ports.evidence_store.get(inputs.tenant_id, outcome.evidence_bundle_ref)
    manifest = EvidenceBundleManifest(**dict(stored.manifest))
    kinds = {entry.kind for entry in manifest.entries}
    assert EvidenceKind.MISSINGNESS_REPORT not in kinds


def test_undetermined_bundle_carries_missingness_report() -> None:
    import dataclasses

    inputs, registration = make_happy_path_inputs()
    bad_inputs = dataclasses.replace(inputs, registration=None)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert outcome.evidence_bundle_complete is False

    stored = ports.evidence_store.get(inputs.tenant_id, outcome.evidence_bundle_ref)
    manifest = EvidenceBundleManifest(**dict(stored.manifest))
    kinds = {entry.kind for entry in manifest.entries}
    assert EvidenceKind.MISSINGNESS_REPORT in kinds


def test_no_raw_customer_content_leaks_into_evidence_entries() -> None:
    """E5 / evidence.py raw-content guard: entries carry refs+hashes only."""
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(inputs, ports, policies)

    stored = ports.evidence_store.get(inputs.tenant_id, outcome.evidence_bundle_ref)
    manifest = EvidenceBundleManifest(**dict(stored.manifest))
    for entry in manifest.entries:
        # Every ref is a URI/content-hash pair, never inline raw content —
        # constructing the manifest at all already ran every entry through
        # `guard_evidence_fields` (evidence.py), so reaching this point with
        # a populated manifest is itself the guard's pass signal; this
        # assertion pins the observable shape as a regression pin.
        assert entry.ref.uri
        assert entry.ref.content_hash.startswith("sha256:")

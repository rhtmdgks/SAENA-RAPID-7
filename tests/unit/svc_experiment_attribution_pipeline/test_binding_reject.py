"""Binding rejects (E1) -> UNDETERMINED with binding reason codes; evidence
bundle still sealed (honest, incomplete, carries a missingness_report)."""

from __future__ import annotations

import dataclasses

from pipeline_factories import (
    make_happy_path_inputs,
    make_policies,
    make_ports,
)
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement


def test_absent_registration_is_undetermined_never_pass() -> None:
    inputs, registration = make_happy_path_inputs()
    bad_inputs = dataclasses.replace(inputs, registration=None)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.IDENTITY_MISMATCH in outcome.reason_codes


def test_cross_tenant_registration_is_undetermined() -> None:
    inputs, registration = make_happy_path_inputs()
    wrong_tenant_registration = registration.model_copy(update={"tenant_id": "globex-co"})
    bad_inputs = dataclasses.replace(inputs, registration=wrong_tenant_registration)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.IDENTITY_MISMATCH in outcome.reason_codes


def test_post_registration_mutation_is_undetermined() -> None:
    inputs, registration = make_happy_path_inputs()
    # Mutate the anchored hash the submission presents -> the registration no
    # longer re-derives to it (post_registration_mutation).
    tampered_submission = inputs.submission.model_copy(
        update={"anchored_hash": "sha256:" + "9" * 64}
    )
    bad_inputs = dataclasses.replace(inputs, submission=tampered_submission)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.POST_REGISTRATION_METRIC_MUTATION in outcome.reason_codes


def test_cell_mismatch_is_undetermined() -> None:
    from pipeline_factories import make_submission
    from saena_domain.measurement.binding import MeasurementCell, Observation

    inputs, registration = make_happy_path_inputs()
    bad_cell = MeasurementCell(
        locale="fr-FR",  # differs from the registered locale
        browser_policy=registration.browser_policy,
        query_cluster_ref=registration.query_cluster_ref,
        repeat_count=registration.repeat_count,
    )
    observations = (
        Observation(observation_id="obs-base-1", arm_id="arm-base", cell=bad_cell),
        Observation(
            observation_id="obs-treat-1",
            arm_id="arm-treat",
            cell=bad_cell,
            asset_hash=registration.asset_hash,
        ),
        Observation(
            observation_id="obs-ctrl-1",
            arm_id="arm-ctrl",
            cell=bad_cell,
            asset_hash=registration.asset_hash,
        ),
    )
    submission = make_submission(registration, observations=observations)
    bad_inputs = dataclasses.replace(inputs, submission=submission)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.CELL_MISMATCH in outcome.reason_codes


def test_contamination_is_undetermined() -> None:
    from pipeline_factories import make_submission
    from saena_domain.measurement.binding import MeasurementCell, Observation

    inputs, registration = make_happy_path_inputs()
    cell = MeasurementCell(
        locale=registration.locale,
        browser_policy=registration.browser_policy,
        query_cluster_ref=registration.query_cluster_ref,
        repeat_count=registration.repeat_count,
    )
    # Same observation_id claimed by two different arms -> contamination.
    observations = (
        Observation(observation_id="obs-base-1", arm_id="arm-base", cell=cell),
        Observation(
            observation_id="obs-shared",
            arm_id="arm-treat",
            cell=cell,
            asset_hash=registration.asset_hash,
        ),
        Observation(
            observation_id="obs-shared",
            arm_id="arm-ctrl",
            cell=cell,
            asset_hash=registration.asset_hash,
        ),
    )
    submission = make_submission(registration, observations=observations)
    bad_inputs = dataclasses.replace(inputs, submission=submission)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.TREATMENT_CONTROL_CONTAMINATION in outcome.reason_codes


def test_binding_reject_still_seals_incomplete_bundle_with_missingness_report() -> None:
    inputs, registration = make_happy_path_inputs()
    bad_inputs = dataclasses.replace(inputs, registration=None)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.evidence_bundle_ref is not None
    assert outcome.evidence_bundle_complete is False

    from saena_domain.measurement.evidence import EvidenceBundleManifest, EvidenceKind

    stored = ports.evidence_store.get(inputs.tenant_id, outcome.evidence_bundle_ref)
    manifest = EvidenceBundleManifest(**dict(stored.manifest))
    kinds = {entry.kind for entry in manifest.entries}
    assert EvidenceKind.MISSINGNESS_REPORT in kinds
    assert EvidenceKind.REGISTRATION not in kinds


def test_binding_reject_never_passes_even_with_two_qualifying_signals() -> None:
    """Binding failing must demote a PASS the B-gate would otherwise compute
    from whatever signals happen to be supplied — E1 is a hard boundary."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    bad_inputs = dataclasses.replace(inputs, registration=None)
    ports = make_ports()
    policies = make_policies(registration)

    outcome = run_measurement(bad_inputs, ports, policies)

    assert outcome.status is not OutcomeStatus.PASS
    assert outcome.status is OutcomeStatus.UNDETERMINED


# --- reason-code precision for the 3 binding reject reasons that the earlier
# suite did not drive through run_measurement (critic w5-13 should-fix): pin
# the exact ReasonCode so a wrong _BINDING_REASON_MAP_STRICT entry is caught,
# not just the (always-correct) UNDETERMINED status. ---


def test_conflicting_registration_is_undetermined_with_mutation_reason() -> None:
    inputs, registration = make_happy_path_inputs()
    # Same experiment_id/anchored_hash, but a different content_fingerprint than
    # the registration's own -> conflicting_registration (binding.py:482).
    tampered = inputs.submission.model_copy(
        update={"content_fingerprint": "cf-does-not-match-registration"}
    )
    bad_inputs = dataclasses.replace(inputs, submission=tampered)
    outcome = run_measurement(bad_inputs, make_ports(), make_policies(registration))

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.POST_REGISTRATION_METRIC_MUTATION in outcome.reason_codes


def test_metric_mutation_is_undetermined_with_mutation_reason() -> None:
    from saena_domain.measurement.binding import MeasurementMetricInput

    inputs, registration = make_happy_path_inputs()
    metric = registration.metric_definitions[0]
    # Registered metric id, but an altered metric_hash -> metric_mutation
    # (binding rejects a definition whose fingerprint no longer matches).
    tampered = inputs.submission.model_copy(
        update={
            "metrics": (
                MeasurementMetricInput(
                    metric_id=metric.metric_id,
                    metric_hash="sha256:" + "a" * 64,
                    weight=1.0,
                ),
            )
        }
    )
    bad_inputs = dataclasses.replace(inputs, submission=tampered)
    outcome = run_measurement(bad_inputs, make_ports(), make_policies(registration))

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.POST_REGISTRATION_METRIC_MUTATION in outcome.reason_codes


def test_asset_hash_conflict_is_undetermined_with_asset_reason() -> None:
    from pipeline_factories import make_submission
    from saena_domain.measurement.binding import MeasurementCell, Observation

    inputs, registration = make_happy_path_inputs()
    cell = MeasurementCell(
        locale=registration.locale,
        browser_policy=registration.browser_policy,
        query_cluster_ref=registration.query_cluster_ref,
        repeat_count=registration.repeat_count,
    )
    # A treatment observation whose asset_hash differs from the registered one
    # -> asset_hash_conflict (binding.py:429).
    observations = (
        Observation(observation_id="obs-base-1", arm_id="arm-base", cell=cell),
        Observation(
            observation_id="obs-treat-1",
            arm_id="arm-treat",
            cell=cell,
            asset_hash="sha256:" + "b" * 64,
        ),
        Observation(
            observation_id="obs-ctrl-1",
            arm_id="arm-ctrl",
            cell=cell,
            asset_hash=registration.asset_hash,
        ),
    )
    submission = make_submission(registration, observations=observations)
    bad_inputs = dataclasses.replace(inputs, submission=submission)
    outcome = run_measurement(bad_inputs, make_ports(), make_policies(registration))

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.ASSET_HASH_CONFLICT in outcome.reason_codes

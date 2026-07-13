"""Conflicting replay (w5-20 deliverable 2, bullet 4): same idempotency key,
DIFFERENT content -> fail-closed, first wins, never arbitrary.

Four layers, each against REAL Postgres or the real domain validator (never
a mock standing in for the fail-closed decision):

1. Confirmation STORE: `PgConfirmationStore.put_confirmation` — same key,
   different payload -> `IdempotencyConflictError`, first content survives.
2. Confirmation VALIDATION: `validate_confirmation` — same idempotency key,
   different confirmation content -> `Rejected(CONFLICTING_REPLAY)`, the
   PRIOR accepted state is what a caller must keep trusting (this module does
   not mutate prior_confirmations on a Rejected — the function is pure).
3. Evidence bundle STORE (content-addressed): same `manifest_hash`, different
   manifest bytes -> `EvidenceHashMismatchError` — this is a stronger
   guarantee than "first wins" (a content-addressed hash collision is treated
   as a corruption/attack signal, never resolved either way).
4. PIPELINE level: `run_measurement` fed a conflicting confirmation (same
   idempotency key, different commit sha) after a first successful run ->
   `ReasonCode.CONFLICTING_CONFIRMATION`, status UNDETERMINED, never PASS —
   proven end-to-end against the real Postgres-backed ports.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from measurement_failure_factories import make_pg_ports
from pipeline_factories import (
    AlwaysTrustVerifier,
    make_deployment_confirmation,
    make_happy_path_inputs,
    make_policies,
    make_registration,
    make_registration_view,
    make_submission,
)
from saena_domain.measurement.confirmation import Rejected, RejectionReason, validate_confirmation
from saena_domain.measurement.errors import (
    EvidenceHashMismatchError,
    IdempotencyConflictError,
)
from saena_domain.measurement.ports import ConfirmationRecord, EvidenceBundle
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement
from saena_experiment_attribution.pipeline.inputs import MeasurementInputs

pytestmark = pytest.mark.integration

_TENANT = "acme-co"


# --- 1. Confirmation store: fail-closed conflict, first content wins -------


def test_confirmation_store_conflicting_content_fails_closed_first_wins(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    ports = make_pg_ports(postgres_url)
    first = ConfirmationRecord(
        tenant_id=_TENANT,
        confirmation_key="idem-conflict",
        measurement_kind="deployment_confirmation",
        payload={"commit": "c1"},
    )
    ports.confirmation_store.put_confirmation(_TENANT, "idem-conflict", first)

    second = ConfirmationRecord(
        tenant_id=_TENANT,
        confirmation_key="idem-conflict",
        measurement_kind="deployment_confirmation",
        payload={"commit": "c2"},  # different content, same key
    )
    with pytest.raises(IdempotencyConflictError):
        ports.confirmation_store.put_confirmation(_TENANT, "idem-conflict", second)

    # First content is still the one on record — never arbitrarily replaced.
    got = ports.confirmation_store.get(_TENANT, "idem-conflict")
    assert got == first
    assert got.payload["commit"] == "c1"


# --- 2. Confirmation validation: Rejected(CONFLICTING_REPLAY), pure --------


def test_validate_confirmation_conflicting_content_is_rejected_not_arbitrary() -> None:
    registration = make_registration()
    registration_view = make_registration_view(registration)
    first_confirmation = make_deployment_confirmation(registration, registration_view)
    server_received_at = first_confirmation.confirmed_at + timedelta(seconds=5)

    accepted = validate_confirmation(
        first_confirmation, registration_view, server_received_at, AlwaysTrustVerifier(), {}
    )
    prior_state = {first_confirmation.idempotency_key: accepted}

    conflicting_confirmation = make_deployment_confirmation(
        registration,
        registration_view,
        idempotency_key=first_confirmation.idempotency_key,
        confirmed_at=first_confirmation.confirmed_at + timedelta(minutes=1),
    )
    verdict = validate_confirmation(
        conflicting_confirmation,
        registration_view,
        server_received_at + timedelta(minutes=1),
        AlwaysTrustVerifier(),
        prior_state,
    )

    assert isinstance(verdict, Rejected)
    assert verdict.reason_code is RejectionReason.CONFLICTING_REPLAY
    # prior_state (a caller-owned mapping) is untouched — validate_confirmation
    # is pure and never mutates the caller's prior-state view.
    assert prior_state[first_confirmation.idempotency_key] == accepted


# --- 3. Evidence bundle: content-addressed, hash collision NEVER resolved --


def test_evidence_bundle_content_addressed_collision_never_silently_resolved(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    ports = make_pg_ports(postgres_url)
    manifest_hash = "sha256:" + "e" * 64
    first_bundle = EvidenceBundle(tenant_id=_TENANT, manifest={"entries": [1], "note": "first"})
    ports.evidence_store.put(_TENANT, manifest_hash, first_bundle)

    colliding_bundle = EvidenceBundle(
        tenant_id=_TENANT, manifest={"entries": [2], "note": "DIFFERENT"}
    )
    with pytest.raises(EvidenceHashMismatchError):
        ports.evidence_store.put(_TENANT, manifest_hash, colliding_bundle)

    got = ports.evidence_store.get(_TENANT, manifest_hash)
    assert got.manifest["note"] == "first"


# --- 4. Pipeline level: conflicting deployment.confirmed -> UNDETERMINED ---


def test_pipeline_conflicting_confirmation_replay_is_undetermined_never_pass(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """A second `run_measurement` invocation for a DIFFERENT run_id sharing
    the FIRST run's idempotency_key, but with different confirmation content
    (different commit sha), must resolve UNDETERMINED(conflicting_confirmation)
    — never silently accepted as a second, arbitrary winner, and never PASS."""
    inputs, registration = make_happy_path_inputs()
    policies = make_policies(registration)
    ports = make_pg_ports(postgres_url)

    run_measurement(inputs, ports, policies)  # first run: establishes the accepted confirmation

    registration_view = inputs.registration_view
    conflicting_confirmation = make_deployment_confirmation(
        registration,
        registration_view,
        idempotency_key=inputs.deployment_confirmation.idempotency_key,
        confirmed_at=inputs.deployment_confirmation.confirmed_at + timedelta(minutes=1),
    )
    # prior_confirmations must reflect the FIRST run's accepted verdict for
    # the conflict to be detected — reconstruct it the way a real caller
    # (the workflow/service boundary) would: by validating the first
    # confirmation again against the same registration view.
    from saena_domain.measurement.confirmation import validate_confirmation

    first_accepted = validate_confirmation(
        inputs.deployment_confirmation,
        registration_view,
        inputs.server_received_at,
        policies.trust_verifier,
        {},
    )
    prior_state = {inputs.deployment_confirmation.idempotency_key: first_accepted}

    conflicting_inputs = MeasurementInputs(
        tenant_id=inputs.tenant_id,
        run_id=inputs.run_id + "-conflict",
        experiment_id=inputs.experiment_id,
        registration=registration,
        registration_view=registration_view,
        submission=make_submission(registration),
        signals=inputs.signals,
        deployment_confirmation=conflicting_confirmation,
        server_received_at=inputs.server_received_at + timedelta(minutes=1),
        evaluation_at=inputs.evaluation_at,
        prior_confirmations=prior_state,
        grs_inputs=inputs.grs_inputs,
    )

    conflicting_outcome = run_measurement(conflicting_inputs, ports, policies)

    assert conflicting_outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.CONFLICTING_CONFIRMATION in conflicting_outcome.reason_codes

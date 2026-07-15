"""c5-03: conflicting-confirmation seam at the START of run_measurement.

A same-tenant / same-idempotency-key / DIFFERENT-content deployment
confirmation must NOT let the `ConfirmationStore.put_confirmation`
`IdempotencyConflictError` escape run_measurement (its contract raises only
`PipelineError`); it must be caught by TYPE and turned into a deterministic,
fail-closed UNDETERMINED(conflicting_confirmation) outcome that never reaches
PASS, never evaluates the conflicting confirmation as accepted, and never
mutates the first accepted confirmation record.

These are pure-domain (in-memory port) unit tests; the real-Postgres
conformance + concurrent-writer proof lives in the w5-20 failure-mode
integration lane (tests/integration/measurement_failure).
"""

from __future__ import annotations

import dataclasses
import json

from pipeline_factories import (
    make_deployment_confirmation,
    make_happy_path_inputs,
    make_policies,
    make_ports,
    make_registration_view,
)
from saena_domain.measurement.ports import ConfirmationRecord
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement


def _seed_first_confirmation(inputs, ports) -> ConfirmationRecord:
    """Run the happy path once so `ports.confirmation_store` durably holds the
    FIRST confirmation record under this run's idempotency key. Returns that
    stored record for later immutability comparison."""
    run_measurement(inputs, ports, make_policies(inputs.registration))
    key = inputs.deployment_confirmation.idempotency_key
    stored = ports.confirmation_store.get(inputs.tenant_id, key)
    assert stored is not None
    return stored


def test_conflicting_confirmation_is_undetermined_never_pass() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    first = _seed_first_confirmation(inputs, ports)

    # Second run: SAME tenant + SAME idempotency key, DIFFERENT content
    # (different commit sha => different confirmation payload), different run.
    view = make_registration_view(registration)
    conflicting = make_deployment_confirmation(registration, view).model_copy(
        update={"deployed_commit_sha": "b" * 40}
    )
    conflicting_inputs = dataclasses.replace(
        inputs, run_id="run-conflict-2", deployment_confirmation=conflicting
    )

    outcome = run_measurement(conflicting_inputs, ports, make_policies(registration))

    # Fail-closed: UNDETERMINED with the authoritative reason, never PASS.
    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert outcome.status is not OutcomeStatus.PASS
    assert ReasonCode.CONFLICTING_CONFIRMATION in outcome.reason_codes
    # The conflicting confirmation was NOT evaluated as accepted: no B-gate
    # decision was computed and no qualifying layers were credited.
    assert outcome.b_gate_decision is None
    assert outcome.qualifying_layers == ()
    assert outcome.is_production is False

    # First-wins immutability: the store still holds the FIRST record, byte for
    # byte — the conflicting attempt never overwrote or appended a second one.
    still = ports.confirmation_store.get(inputs.tenant_id, first.confirmation_key)
    assert still == first


def test_conflicting_confirmation_bundle_is_incomplete_and_honest() -> None:
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    _seed_first_confirmation(inputs, ports)

    view = make_registration_view(registration)
    conflicting = make_deployment_confirmation(registration, view).model_copy(
        update={"deployed_commit_sha": "c" * 40}
    )
    conflicting_inputs = dataclasses.replace(
        inputs, run_id="run-conflict-3", deployment_confirmation=conflicting
    )

    outcome = run_measurement(conflicting_inputs, ports, make_policies(registration))

    # No partial/contradictory result: the evidence bundle is sealed but
    # explicitly incomplete (never silently completed).
    assert outcome.evidence_bundle_complete is False
    assert outcome.evidence_bundle_ref is not None


def test_conflicting_confirmation_outcome_is_deterministic() -> None:
    """Re-running the identical conflicting attempt yields a byte-identical
    canonical outcome payload (deterministic retry)."""
    inputs, registration = make_happy_path_inputs()

    def _run_conflict() -> str:
        ports = make_ports()
        _seed_first_confirmation(inputs, ports)
        view = make_registration_view(registration)
        conflicting = make_deployment_confirmation(registration, view).model_copy(
            update={"deployed_commit_sha": "d" * 40}
        )
        conflicting_inputs = dataclasses.replace(
            inputs, run_id="run-conflict-4", deployment_confirmation=conflicting
        )
        return run_measurement(
            conflicting_inputs, ports, make_policies(registration)
        ).canonical_payload()

    assert _run_conflict() == _run_conflict()


def test_identical_confirmation_replay_is_not_a_conflict() -> None:
    """A byte-identical confirmation replay must NOT be treated as a conflict:
    the store returns DUPLICATE (no raise) and the run proceeds normally,
    preserving idempotency (same key, same content, same run)."""
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    first_outcome = run_measurement(inputs, ports, make_policies(registration))

    # Exact same inputs again — same key, same content.
    second_outcome = run_measurement(inputs, ports, make_policies(registration))

    assert ReasonCode.CONFLICTING_CONFIRMATION not in second_outcome.reason_codes
    assert second_outcome.canonical_payload() == first_outcome.canonical_payload()


def test_non_conflict_store_errors_still_propagate() -> None:
    """Only `IdempotencyConflictError` is absorbed into a fail-closed outcome.
    Any OTHER store error (integrity/programmer) must still propagate as its
    own typed error — the seam does not swallow unexpected failures."""
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()

    class _BoomStore:
        def put_confirmation(self, *_a, **_k):  # noqa: ANN002, ANN003
            raise RuntimeError("unexpected store failure")

    broken = dataclasses.replace(ports, confirmation_store=_BoomStore())

    try:
        run_measurement(inputs, broken, make_policies(registration))
    except RuntimeError as exc:
        assert "unexpected store failure" in str(exc)
    else:  # pragma: no cover - the call must raise
        raise AssertionError("expected the non-conflict store error to propagate")


def test_seam_never_echoes_confirmation_content_in_reason_codes() -> None:
    """Privacy: the conflict path records only the typed reason code, never
    the conflicting confirmation's raw content (commit sha, signature, ...)."""
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    _seed_first_confirmation(inputs, ports)

    view = make_registration_view(registration)
    secret_sha = "deadbeef" * 5
    conflicting = make_deployment_confirmation(registration, view).model_copy(
        update={"deployed_commit_sha": secret_sha}
    )
    conflicting_inputs = dataclasses.replace(
        inputs, run_id="run-conflict-5", deployment_confirmation=conflicting
    )

    outcome = run_measurement(conflicting_inputs, ports, make_policies(registration))
    # `canonical_payload()` is a dict — `x in dict` only checks KEYS, so
    # serialize the whole structure to search actual nested VALUES (c5-03
    # security should-fix sec-2).
    rendered = json.dumps(outcome.canonical_payload(), sort_keys=True, default=str)
    assert secret_sha not in rendered
    assert "sig-1" not in rendered
    assert "confirmer-1" not in rendered

    # Also assert the STORED evidence bundle (a separate persistence surface
    # from the outcome payload) never carries the raw content — only the
    # confirmation FINGERPRINT (a hash) may appear.
    stored_bundle = ports.evidence_store.get(inputs.tenant_id, outcome.evidence_bundle_ref)
    # `manifest` is a (possibly nested) read-only mapping — stringify the whole
    # structure to search the ACTUAL serialized content, not just top-level keys.
    bundle_blob = repr(dict(stored_bundle.manifest))
    assert secret_sha not in bundle_blob
    assert "sig-1" not in bundle_blob
    assert "confirmer-1" not in bundle_blob


def test_two_unrelated_conflicts_in_same_tenant_do_not_collide_or_crash() -> None:
    """c5-03 security MUST-FIX regression: two DIFFERENT runs in the SAME
    tenant that both hit a confirmation conflict must EACH return a clean
    fail-closed UNDETERMINED — the second must not crash with
    EvidenceHashMismatchError because both conflict bundles hashed
    identically. The per-run confirmation-conflict evidence entry makes each
    manifest_hash unique."""
    inputs, registration = make_happy_path_inputs()
    ports = make_ports()
    _seed_first_confirmation(inputs, ports)

    view = make_registration_view(registration)
    outcomes = []
    # NB: both shas differ from the seed confirmation's default ("a"*40) so
    # each is a genuine same-key/DIFFERENT-content CONFLICT (not a byte-
    # identical DUPLICATE that would replay the full happy path).
    for run_id, sha in (("unrelated-run-A", "1" * 40), ("unrelated-run-B", "2" * 40)):
        conflicting = make_deployment_confirmation(registration, view).model_copy(
            update={"deployed_commit_sha": sha}
        )
        conflicting_inputs = dataclasses.replace(
            inputs, run_id=run_id, deployment_confirmation=conflicting
        )
        # Must NOT raise for either run.
        outcomes.append(run_measurement(conflicting_inputs, ports, make_policies(registration)))

    for outcome in outcomes:
        assert outcome.status is OutcomeStatus.UNDETERMINED
        assert ReasonCode.CONFLICTING_CONFIRMATION in outcome.reason_codes
    # Distinct runs -> distinct evidence bundle refs (no hash collision).
    assert outcomes[0].evidence_bundle_ref != outcomes[1].evidence_bundle_ref

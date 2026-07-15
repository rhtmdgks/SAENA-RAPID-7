"""Pure ``workflow_logic`` unit tests — no Temporal server (mirrors
``tests/unit/svc_orchestrator/test_workflow_logic.py``). Targets ~100% of the
deterministic decision core; the ``@workflow.defn`` shell's live-timer behavior
is proven under a real time-skipping ``WorkflowEnvironment`` in
``tests/integration/measurement_workflow/``.

Guard-mutation intent (wave5-plan.md §Test/evidence): each classification branch
has a discriminating assertion — removing/flipping a guard flips at least one
assertion here.
"""

from __future__ import annotations

from attribution_factories import make_accepted
from saena_experiment_attribution.workflow.workflow_logic import (
    MeasurementOutcomeStatus,
    SignalDisposition,
    WindowBinding,
    aborted_outcome,
    classify_confirmation_signal,
    decided_outcome,
    deployment_late_outcome,
    extract_binding,
)

REGISTRATION_HASH = "sha256:" + "a" * 64


# --------------------------------------------------------------------------- #
# extract_binding
# --------------------------------------------------------------------------- #
def test_extract_binding_uses_confirmation_key_and_accepted_fingerprint() -> None:
    accepted = make_accepted()
    binding = extract_binding(accepted)
    assert binding.idempotency_key == accepted.confirmation.idempotency_key
    assert binding.content_fingerprint == accepted.content_fingerprint


# --------------------------------------------------------------------------- #
# classify_confirmation_signal — every disposition
# --------------------------------------------------------------------------- #
def test_first_valid_confirmation_is_start() -> None:
    accepted = make_accepted()
    disp = classify_confirmation_signal(accepted, None, REGISTRATION_HASH)
    assert disp is SignalDisposition.START


def test_non_accepted_payload_is_refused_structural() -> None:
    # A raw dict / anything that is not an Accepted is refused — the signal
    # contract carries an Accepted reference; nothing else is trusted.
    disp = classify_confirmation_signal({"not": "accepted"}, None, REGISTRATION_HASH)
    assert disp is SignalDisposition.REFUSED_STRUCTURAL


def test_registration_hash_mismatch_is_refused_structural() -> None:
    # An Accepted for a DIFFERENT registration can never re-anchor this run.
    other = make_accepted(registration_hash="sha256:" + "b" * 64)
    disp = classify_confirmation_signal(other, None, REGISTRATION_HASH)
    assert disp is SignalDisposition.REFUSED_STRUCTURAL


def test_registration_mismatch_refused_even_with_existing_binding() -> None:
    accepted = make_accepted()
    binding = extract_binding(accepted)
    other = make_accepted(registration_hash="sha256:" + "b" * 64)
    disp = classify_confirmation_signal(other, binding, REGISTRATION_HASH)
    assert disp is SignalDisposition.REFUSED_STRUCTURAL


def test_identical_replay_is_duplicate_not_restart() -> None:
    accepted = make_accepted()
    binding = extract_binding(accepted)
    # Same key + same fingerprint (byte-identical re-delivery) → DUPLICATE.
    disp = classify_confirmation_signal(accepted, binding, REGISTRATION_HASH)
    assert disp is SignalDisposition.DUPLICATE


def test_same_key_different_content_is_conflicting_replay() -> None:
    first = make_accepted(deployed_commit_sha="commit-first")
    binding = extract_binding(first)
    # Same idempotency key, DIFFERENT commit → different fingerprint → conflict.
    conflicting = make_accepted(deployed_commit_sha="commit-second")
    assert conflicting.confirmation.idempotency_key == first.confirmation.idempotency_key
    assert conflicting.content_fingerprint != first.content_fingerprint
    disp = classify_confirmation_signal(conflicting, binding, REGISTRATION_HASH)
    assert disp is SignalDisposition.CONFLICTING_REPLAY


def test_different_key_colliding_on_run_is_conflicting_replay() -> None:
    # A second confirmation with a DIFFERENT key (a different confirmation
    # entirely) arriving for an already-bound run is first-wins → conflict,
    # never a second START/restart.
    first = make_accepted(idempotency_key="idem-1")
    binding = extract_binding(first)
    second = make_accepted(idempotency_key="idem-2")
    disp = classify_confirmation_signal(second, binding, REGISTRATION_HASH)
    assert disp is SignalDisposition.CONFLICTING_REPLAY


def test_binding_equality_is_value_based() -> None:
    a = WindowBinding(idempotency_key="k", content_fingerprint="fp")
    b = WindowBinding(idempotency_key="k", content_fingerprint="fp")
    assert a == b


# --------------------------------------------------------------------------- #
# outcome constructors
# --------------------------------------------------------------------------- #
def test_deployment_late_outcome_is_undetermined_with_typed_reason() -> None:
    outcome = deployment_late_outcome("idem-late")
    assert outcome.status is MeasurementOutcomeStatus.UNDETERMINED_DEPLOYMENT_LATE
    assert outcome.idempotency_key == "idem-late"
    assert outcome.outcome_ref is None
    assert outcome.reason == "deployment_late"


def test_aborted_outcome_is_undetermined_and_never_dropped() -> None:
    outcome = aborted_outcome("idem-abort")
    assert outcome.status is MeasurementOutcomeStatus.UNDETERMINED_ABORTED
    assert outcome.idempotency_key == "idem-abort"
    assert outcome.outcome_ref is None
    assert outcome.reason == "aborted"


def test_decided_outcome_carries_outcome_ref_and_no_reason() -> None:
    outcome = decided_outcome("idem-decided", "outcome-ref:xyz")
    assert outcome.status is MeasurementOutcomeStatus.DECIDED
    assert outcome.idempotency_key == "idem-decided"
    assert outcome.outcome_ref == "outcome-ref:xyz"
    assert outcome.reason is None


def test_only_decided_status_is_not_undetermined() -> None:
    # UNDETERMINED semantics: DECIDED is the ONLY status carrying a real outcome
    # ref; every other status is an undetermined variant (reason set, ref None).
    for status in MeasurementOutcomeStatus:
        is_undetermined = status is not MeasurementOutcomeStatus.DECIDED
        assert status.value.startswith("undetermined_") is is_undetermined

"""Unit tests for saena_domain.privacy.status transition rules (ADR-0013)."""

from __future__ import annotations

import pytest
from saena_domain.privacy.gate import GateDecision, KAnonymityGate, KAnonymityGateResult
from saena_domain.privacy.status import (
    DeIdentificationTransition,
    GateRequiredForKAnonymizedError,
    InvalidDeIdentificationTransitionError,
    transition,
)
from saena_schemas.envelope.event_envelope_v1 import DeIdentificationStatus

PASSING_GATE = KAnonymityGate.evaluate(cohort_size=12, privacy_threshold=5)
FAILING_GATE = KAnonymityGate.evaluate(cohort_size=3, privacy_threshold=5)


def test_pending_review_to_k_anonymized_requires_passing_gate() -> None:
    result = transition(
        DeIdentificationStatus.pending_review,
        DeIdentificationStatus.k_anonymized,
        gate_result=PASSING_GATE,
    )

    assert result == DeIdentificationTransition(
        from_status=DeIdentificationStatus.pending_review,
        to_status=DeIdentificationStatus.k_anonymized,
    )


def test_pending_review_to_k_anonymized_without_gate_result_rejected() -> None:
    with pytest.raises(GateRequiredForKAnonymizedError):
        transition(
            DeIdentificationStatus.pending_review,
            DeIdentificationStatus.k_anonymized,
        )


def test_pending_review_to_k_anonymized_with_failing_gate_rejected() -> None:
    with pytest.raises(GateRequiredForKAnonymizedError):
        transition(
            DeIdentificationStatus.pending_review,
            DeIdentificationStatus.k_anonymized,
            gate_result=FAILING_GATE,
        )


def test_pending_review_to_suppressed_on_gate_fail_allowed() -> None:
    result = transition(
        DeIdentificationStatus.pending_review,
        DeIdentificationStatus.suppressed,
        gate_result=FAILING_GATE,
    )

    assert result.to_status is DeIdentificationStatus.suppressed


def test_pending_review_to_suppressed_manual_without_gate_allowed() -> None:
    """Manual suppression does not require a gate evaluation at all."""
    result = transition(
        DeIdentificationStatus.pending_review,
        DeIdentificationStatus.suppressed,
    )

    assert result.to_status is DeIdentificationStatus.suppressed


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (DeIdentificationStatus.k_anonymized, DeIdentificationStatus.pending_review),
        (DeIdentificationStatus.k_anonymized, DeIdentificationStatus.suppressed),
        (DeIdentificationStatus.suppressed, DeIdentificationStatus.pending_review),
        (DeIdentificationStatus.suppressed, DeIdentificationStatus.k_anonymized),
        (DeIdentificationStatus.k_anonymized, DeIdentificationStatus.k_anonymized),
        (DeIdentificationStatus.suppressed, DeIdentificationStatus.suppressed),
        (DeIdentificationStatus.pending_review, DeIdentificationStatus.pending_review),
    ],
)
def test_invalid_transitions_rejected(
    from_status: DeIdentificationStatus, to_status: DeIdentificationStatus
) -> None:
    with pytest.raises(InvalidDeIdentificationTransitionError):
        transition(from_status, to_status)


def test_invalid_transition_error_carries_endpoints() -> None:
    with pytest.raises(InvalidDeIdentificationTransitionError) as exc_info:
        transition(DeIdentificationStatus.k_anonymized, DeIdentificationStatus.suppressed)

    assert exc_info.value.from_status is DeIdentificationStatus.k_anonymized
    assert exc_info.value.to_status is DeIdentificationStatus.suppressed


def test_gate_result_type_is_reused_from_gate_module() -> None:
    assert isinstance(PASSING_GATE, KAnonymityGateResult)
    assert PASSING_GATE.decision is GateDecision.ALLOWED

"""Unit tests for saena_domain.privacy.gate.KAnonymityGate (ADR-0013)."""

from __future__ import annotations

import pytest
from saena_domain.privacy.gate import GateDecision, KAnonymityGate, KAnonymityGateResult


def test_cohort_above_threshold_allowed() -> None:
    result = KAnonymityGate.evaluate(cohort_size=12, privacy_threshold=5)

    assert result.decision is GateDecision.ALLOWED
    assert result.allowed is True
    assert result.reason == "cohort_size_meets_threshold"


def test_cohort_equal_to_threshold_is_boundary_pass() -> None:
    """ADR-0013: k-anonymity is 'at least k' — cohort_size == threshold ALLOWS."""
    result = KAnonymityGate.evaluate(cohort_size=5, privacy_threshold=5)

    assert result.decision is GateDecision.ALLOWED
    assert result.allowed is True


def test_cohort_below_threshold_suppressed() -> None:
    """Mirrors tests/contract/fixtures/envelope/invalid/cohort-below-threshold.json."""
    result = KAnonymityGate.evaluate(cohort_size=3, privacy_threshold=5)

    assert result.decision is GateDecision.SUPPRESSED
    assert result.allowed is False
    assert result.reason == "cohort_size_below_threshold"


def test_result_is_immutable_and_carries_inputs() -> None:
    result = KAnonymityGate.evaluate(cohort_size=8, privacy_threshold=8)

    assert isinstance(result, KAnonymityGateResult)
    assert result.cohort_size == 8
    assert result.privacy_threshold == 8
    with pytest.raises(AttributeError):
        result.decision = GateDecision.SUPPRESSED  # type: ignore[misc]


@pytest.mark.parametrize("cohort_size", [0, -1, -100])
def test_cohort_size_below_schema_minimum_rejected(cohort_size: int) -> None:
    """Schema minimum is 1 (event-envelope v1 aggregateContextEnvelope.cohort_size)."""
    with pytest.raises(ValueError, match="cohort_size"):
        KAnonymityGate.evaluate(cohort_size=cohort_size, privacy_threshold=5)


@pytest.mark.parametrize("privacy_threshold", [0, -1, -100])
def test_privacy_threshold_below_schema_minimum_rejected(privacy_threshold: int) -> None:
    """Schema minimum is 1 (event-envelope v1 aggregateContextEnvelope.privacy_threshold)."""
    with pytest.raises(ValueError, match="privacy_threshold"):
        KAnonymityGate.evaluate(cohort_size=5, privacy_threshold=privacy_threshold)


def test_cohort_size_at_minimum_boundary_allowed_when_threshold_matches() -> None:
    result = KAnonymityGate.evaluate(cohort_size=1, privacy_threshold=1)

    assert result.decision is GateDecision.ALLOWED


def test_missing_threshold_none_rejected() -> None:
    """Bypass-avoidance: a caller must not be able to pass a missing threshold."""
    with pytest.raises(TypeError, match="privacy_threshold"):
        KAnonymityGate.evaluate(cohort_size=12, privacy_threshold=None)  # type: ignore[arg-type]


def test_missing_cohort_size_none_rejected() -> None:
    with pytest.raises(TypeError, match="cohort_size"):
        KAnonymityGate.evaluate(cohort_size=None, privacy_threshold=5)  # type: ignore[arg-type]


def test_non_int_cohort_size_rejected() -> None:
    with pytest.raises(TypeError, match="cohort_size"):
        KAnonymityGate.evaluate(cohort_size="12", privacy_threshold=5)  # type: ignore[arg-type]


def test_non_int_privacy_threshold_rejected() -> None:
    with pytest.raises(TypeError, match="privacy_threshold"):
        KAnonymityGate.evaluate(cohort_size=12, privacy_threshold="5")  # type: ignore[arg-type]


def test_bool_cohort_size_rejected() -> None:
    """bool is an int subclass in Python — must not silently pass as 1/0."""
    with pytest.raises(TypeError, match="cohort_size"):
        KAnonymityGate.evaluate(cohort_size=True, privacy_threshold=1)  # type: ignore[arg-type]


def test_huge_threshold_far_above_cohort_suppressed() -> None:
    result = KAnonymityGate.evaluate(cohort_size=10, privacy_threshold=1_000_000)

    assert result.decision is GateDecision.SUPPRESSED

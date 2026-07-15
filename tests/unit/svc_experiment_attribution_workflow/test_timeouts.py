"""``timeouts`` unit tests — resilience.md coherence invariants (mirrors
``tests/unit/svc_orchestrator/test_timeouts.py``)."""

from __future__ import annotations

import pytest
from saena_domain.measurement.clock import MeasurementPolicy
from saena_experiment_attribution.workflow.timeouts import (
    ACTIVITY_START_TO_CLOSE_TIMEOUT,
    ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS,
    BUFFER_SECONDS,
    COLLECT_AND_DECIDE_DEADLINE_SECONDS,
    DEFAULT_WINDOW_DAYS,
    HEARTBEAT_TIMEOUT,
    HEARTBEAT_TIMEOUT_SECONDS,
    validate_timeout_heartbeat_coherence,
)


def test_start_to_close_is_deadline_plus_buffer() -> None:
    assert (
        ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS
        == COLLECT_AND_DECIDE_DEADLINE_SECONDS + BUFFER_SECONDS
    )
    assert ACTIVITY_START_TO_CLOSE_TIMEOUT.total_seconds() == (
        ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS
    )


def test_start_to_close_at_least_deadline_plus_buffer() -> None:
    # The resilience.md bound: startToCloseTimeout >= deadline + buffer.
    assert (
        ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS
        >= COLLECT_AND_DECIDE_DEADLINE_SECONDS + BUFFER_SECONDS
    )


def test_heartbeat_strictly_less_than_start_to_close() -> None:
    assert HEARTBEAT_TIMEOUT_SECONDS < ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS
    assert HEARTBEAT_TIMEOUT.total_seconds() < ACTIVITY_START_TO_CLOSE_TIMEOUT.total_seconds()


def test_coherence_validator_passes_for_module_constants() -> None:
    # Must not raise for the shipped constants (startup-time invariant).
    validate_timeout_heartbeat_coherence()


def test_default_window_days_matches_domain_policy_default() -> None:
    # The workflow's default-policy window fallback constant must equal the
    # domain MeasurementPolicy default (7 days) — no drift between the two.
    assert DEFAULT_WINDOW_DAYS == MeasurementPolicy().window_days == 7


def test_coherence_validator_detects_bad_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    # Guard-mutation: if heartbeat >= start-to-close the validator MUST raise.
    import saena_experiment_attribution.workflow.timeouts as t

    monkeypatch.setattr(t, "HEARTBEAT_TIMEOUT_SECONDS", t.ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS)
    with pytest.raises(AssertionError):
        t.validate_timeout_heartbeat_coherence()

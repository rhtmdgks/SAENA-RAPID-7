"""Timeout/heartbeat constant assertions — W2B exit gate (task instruction:
"make it a concrete asserted test")."""

from __future__ import annotations

from datetime import timedelta

import pytest
from saena_orchestrator import timeouts


def test_start_to_close_timeout_meets_w2b_exit_gate_bound() -> None:
    # docs/architecture/implementation-waves.md W2B exit: Activity
    # startToCloseTimeout >= 7200s+buffer.
    assert timeouts.ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS >= 7200 + timeouts.BUFFER_SECONDS
    assert timeouts.RUNNER_JOB_ACTIVE_DEADLINE_SECONDS == 7200


def test_start_to_close_timeout_matches_timedelta() -> None:
    assert (
        timedelta(seconds=timeouts.ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS)
        == timeouts.ACTIVITY_START_TO_CLOSE_TIMEOUT
    )
    assert timedelta(seconds=timeouts.HEARTBEAT_TIMEOUT_SECONDS) == timeouts.HEARTBEAT_TIMEOUT


def test_heartbeat_timeout_is_strictly_less_than_start_to_close() -> None:
    assert timeouts.HEARTBEAT_TIMEOUT_SECONDS < timeouts.ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS


def test_validate_timeout_heartbeat_coherence_passes_for_module_constants() -> None:
    # Must not raise for this module's own committed constants.
    timeouts.validate_timeout_heartbeat_coherence()


def test_validate_timeout_heartbeat_coherence_rejects_undersized_start_to_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(timeouts, "ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS", 100)
    with pytest.raises(AssertionError):
        timeouts.validate_timeout_heartbeat_coherence()


def test_validate_timeout_heartbeat_coherence_rejects_heartbeat_not_less_than_start_to_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        timeouts, "HEARTBEAT_TIMEOUT_SECONDS", timeouts.ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS
    )
    with pytest.raises(AssertionError):
        timeouts.validate_timeout_heartbeat_coherence()

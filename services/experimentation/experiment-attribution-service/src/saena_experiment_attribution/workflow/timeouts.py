"""Activity timeout/heartbeat constants for the measurement workflow.

Mirrors ``saena_orchestrator.timeouts`` (resilience.md:19 conventions:
"startToCloseTimeout >= deadline + buffer", heartbeat « start-to-close). The
measurement workflow's activities are SHORT (window derivation is a pure domain
call + a registration lookup; collect-and-decide is a bounded DiD/B-gate batch),
NOT a 7200s runner Job — so the deadline basis here is the collect-and-decide
batch deadline, not the k3s runner ``activeDeadlineSeconds``. The 7-day duration
is a WORKFLOW ``sleep`` (a durable timer), NOT an activity timeout — an activity
must never be held open for the window; that would defeat the durable-timer
design (single timer, no polling loop).

The two coherence invariants (``validate_timeout_heartbeat_coherence``) match
the orchestrator's: start-to-close >= deadline + buffer, and heartbeat strictly
< start-to-close so a stalled activity is detected before its own deadline.
"""

from __future__ import annotations

from datetime import timedelta

# Deadline basis: the collect-and-decide activity's own bounded compute budget
# (DiD + B-gate + evidence-bundle assembly over an already-collected window's
# observations). This is a batch computation, not a live long-running Job — a
# generous but bounded 30-minute deadline. This is THIS unit's concrete choice
# (resilience.md supplies the formula shape, not this specific number for a
# measurement-decide activity).
COLLECT_AND_DECIDE_DEADLINE_SECONDS: int = 1800

# resilience.md: startToCloseTimeout >= deadline + buffer. Buffer absorbs
# activity scheduling/dispatch latency beyond the batch deadline without
# masking a genuinely hung activity.
BUFFER_SECONDS: int = 300

ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS: int = COLLECT_AND_DECIDE_DEADLINE_SECONDS + BUFFER_SECONDS
ACTIVITY_START_TO_CLOSE_TIMEOUT: timedelta = timedelta(
    seconds=ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS
)

# Heartbeat interval: a small fraction of start-to-close (heartbeat « start-to-
# close, never >=, per resilience.md and the orchestrator precedent) so a
# stalled collect-and-decide activity is detected well before its own deadline.
HEARTBEAT_TIMEOUT_SECONDS: int = 30
HEARTBEAT_TIMEOUT: timedelta = timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)

# The durable 7-day measurement window duration (a WORKFLOW sleep, not an
# activity timeout). Kept here as the single named constant the workflow shell
# sleeps for when the domain policy is the default (7 days). The authoritative
# per-run window end is ``MeasurementWindow.end`` (from the derive_window
# activity); this constant is only the default-policy fallback / documentation
# anchor and is asserted consistent with ``MeasurementPolicy`` defaults in the
# unit tests.
DEFAULT_WINDOW_DAYS: int = 7


def validate_timeout_heartbeat_coherence() -> None:
    """Assert the resilience.md bound + heartbeat/start-to-close coherence.

    Raises ``AssertionError`` (a startup-time configuration invariant, not a
    runtime decision — same discipline as ``saena_orchestrator.timeouts``) if
    either start-to-close < deadline + buffer, or heartbeat >= start-to-close.
    Called at workflow/activity wiring import time and asserted directly in the
    unit tests.
    """
    assert (
        ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS
        >= COLLECT_AND_DECIDE_DEADLINE_SECONDS + BUFFER_SECONDS
    ), (
        "ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS must be >= "
        "COLLECT_AND_DECIDE_DEADLINE_SECONDS + BUFFER_SECONDS (resilience.md)"
    )
    assert HEARTBEAT_TIMEOUT_SECONDS < ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS, (
        "HEARTBEAT_TIMEOUT_SECONDS must be strictly less than "
        "ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS (heartbeat must detect a "
        "stall before the start-to-close deadline)"
    )


__all__ = [
    "ACTIVITY_START_TO_CLOSE_TIMEOUT",
    "ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS",
    "BUFFER_SECONDS",
    "COLLECT_AND_DECIDE_DEADLINE_SECONDS",
    "DEFAULT_WINDOW_DAYS",
    "HEARTBEAT_TIMEOUT",
    "HEARTBEAT_TIMEOUT_SECONDS",
    "validate_timeout_heartbeat_coherence",
]

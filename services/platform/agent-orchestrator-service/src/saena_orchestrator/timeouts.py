"""Activity timeout/heartbeat constants — W2B exit gate.

Source: `docs/architecture/resilience.md` ("Temporal Activity <-> K8s Job
정합: runner Job을 감싸는 Activity는 `startToCloseTimeout >=
activeDeadlineSeconds(7200s) + buffer`, heartbeat interval = Job 상태 poll
주기") and `docs/architecture/implementation-waves.md` W2B exit ("Activity
`startToCloseTimeout >= 7200s+buffer` + heartbeat 정합"), which is the
CONFIRMED planning-level gate; resilience.md itself is status PROPOSED (its
own header) but is the only document that supplies the concrete formula, and
implementation-waves.md's W2B exit criterion makes the `>= 7200 + buffer`
bound binding for this patch unit regardless of resilience.md's own
document-status. `7200` itself is `activeDeadlineSeconds` from
`docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` (k3s spec, CONFIRMED,
§5.3 / runner Job manifest example) — READ ONLY basis, not redefined here.

This module owns only the Activity-side timeout/heartbeat numbers the
orchestrator's Temporal Activity wrapping a runner Job must configure. It does
not define or duplicate the k3s Job's own `activeDeadlineSeconds` (that is a
k3s spec/Job-manifest concern, out of this package's scope) — it treats 7200
as an imported constant of the *runner Job's* deadline that the Activity
wrapping it must outlive.

Heartbeat/start-to-close ratio: `HEARTBEAT_TIMEOUT_SECONDS` is deliberately a
small fraction of `ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS` (heartbeat must be
« start-to-close, never >=, or a single missed poll tick would starve
Temporal's own liveness detection before the Activity's real deadline is even
reached). `HEARTBEAT_TIMEOUT_SECONDS` here approximates "Job 상태 poll 주기"
(resilience.md) as a conservative default poll interval bound; the concrete
K8s Job-status poll cadence is an execution-time (W3) concern — this constant
is this Activity wrapper's own heartbeat contract, independent of the actual
poll implementation that lands with the real runner Activity in W3.
"""

from __future__ import annotations

from datetime import timedelta

# k3s spec §5.3 runner Job manifest example: activeDeadlineSeconds = 7200.
RUNNER_JOB_ACTIVE_DEADLINE_SECONDS: int = 7200

# resilience.md: "startToCloseTimeout >= activeDeadlineSeconds(7200s) +
# buffer". BUFFER_SECONDS is this module's own named buffer — chosen large
# enough to absorb Activity scheduling/dispatch latency and K8s Job-status
# poll lag beyond the Job's own deadline, without being so large it masks a
# genuinely hung Activity. 600s (10 min) is this patch unit's concrete choice
# for that buffer; resilience.md does not specify a number.
BUFFER_SECONDS: int = 600

# The W2B exit-gate bound itself: startToCloseTimeout >= 7200 + buffer.
ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS: int = RUNNER_JOB_ACTIVE_DEADLINE_SECONDS + BUFFER_SECONDS
ACTIVITY_START_TO_CLOSE_TIMEOUT: timedelta = timedelta(
    seconds=ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS
)

# Heartbeat interval approximating "Job 상태 poll 주기" (resilience.md).
# Chosen as a small fraction of the start-to-close timeout (heartbeat_timeout
# must be « start_to_close_timeout, see module docstring) so Temporal detects
# a stalled Activity (no heartbeat) long before the 7200s+buffer deadline
# would otherwise be reached.
HEARTBEAT_TIMEOUT_SECONDS: int = 30
HEARTBEAT_TIMEOUT: timedelta = timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)


def validate_timeout_heartbeat_coherence() -> None:
    """Assert the W2B exit-gate bound + heartbeat/start-to-close coherence.

    Raises AssertionError (not a domain error — this is a startup-time
    configuration invariant, not a runtime decision) if either:
      - start_to_close_timeout < 7200 + buffer (the W2B exit gate itself), or
      - heartbeat_timeout >= start_to_close_timeout (heartbeat must be
        strictly smaller, or it cannot detect a stall before the deadline).

    Called by the workflow/activity wiring at import/startup time and
    asserted directly in tests (task instruction: "make it a concrete
    asserted test").
    """
    assert (
        ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS
        >= RUNNER_JOB_ACTIVE_DEADLINE_SECONDS + BUFFER_SECONDS
    ), (
        "ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS must be >= "
        "RUNNER_JOB_ACTIVE_DEADLINE_SECONDS + BUFFER_SECONDS (W2B exit gate)"
    )
    assert HEARTBEAT_TIMEOUT_SECONDS < ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS, (
        "HEARTBEAT_TIMEOUT_SECONDS must be strictly less than "
        "ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS (heartbeat must be able to "
        "detect a stall before the start-to-close deadline)"
    )


__all__ = [
    "ACTIVITY_START_TO_CLOSE_TIMEOUT",
    "ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS",
    "BUFFER_SECONDS",
    "HEARTBEAT_TIMEOUT",
    "HEARTBEAT_TIMEOUT_SECONDS",
    "RUNNER_JOB_ACTIVE_DEADLINE_SECONDS",
    "validate_timeout_heartbeat_coherence",
]

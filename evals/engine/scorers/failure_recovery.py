"""Axis 5 — failure recovery: "a failure mode recovers to a defined
retryable state", scored over REAL `saena_domain.execution` code (`JobError`,
`JobStatus`, `transition`).

The domain's OWN defined recovery contract (not invented by this scorer):

  - `JobError.retryable=True`  -> the only legitimate recovery is a NEW job
    instance starting at `JobStatus.PENDING` (never resuming the SAME failed
    job in place — `FAILED` has an empty transition adjacency set, see
    `saena_domain.execution.lifecycle`), which must then be able to progress
    `PENDING -> RUNNING` via the real `transition()` function.
  - `JobError.retryable=False` -> no recovery is attempted; the failed job
    stays terminal at `FAILED` and an in-place `FAILED -> PENDING` attempt
    on the SAME job must be REJECTED by `transition()` (real
    `InvalidJobTransitionError`, asserted directly here, not assumed).

Fixture `input.recovery_strategy` is one of `"new_job"` (spawn a separate
job at `PENDING`) or `"resume_same_job"` (illegal in-place transition,
attempted directly against the ALREADY-FAILED job) — the two
`false_positive_guard`/`false_negative_guard` fixtures pair a mismatched
`(retryable, recovery_strategy)` combination to prove this axis rejects
both "silently retried a non-retryable failure" and "recovered via an
illegal same-job transition instead of a new job".
"""

from __future__ import annotations

from saena_domain.execution import (
    InvalidJobTransitionError,
    JobError,
    JobStatus,
    transition,
)

from evals.engine.fixture import Fixture
from evals.engine.result import ScoreResult


def score(fixture: Fixture) -> ScoreResult:
    error_raw = fixture.input["error"]
    job_error = JobError(
        error_code=error_raw["error_code"],
        summary=error_raw["summary"],
        retryable=bool(error_raw["retryable"]),
    )
    recovery_strategy = fixture.input["recovery_strategy"]

    if recovery_strategy == "new_job":
        if not job_error.retryable:
            return ScoreResult(
                passed=False,
                score=0.0,
                reasons=(
                    f"error {job_error.error_code!r} is retryable=False but was retried "
                    "via a new job — a non-retryable failure must not be silently retried",
                ),
            )
        outcome = transition(JobStatus.PENDING, JobStatus.RUNNING)
        if not outcome.changed or outcome.status != JobStatus.RUNNING:
            return ScoreResult(
                passed=False,
                score=0.0,
                reasons=("new recovery job failed to progress PENDING -> RUNNING",),
            )
        return ScoreResult(passed=True, score=1.0, reasons=())

    if recovery_strategy == "resume_same_job":
        try:
            transition(JobStatus.FAILED, JobStatus.PENDING)
        except InvalidJobTransitionError:
            # Correctly rejected — but "resume_same_job" itself is never a
            # DEFINED recovery state regardless of retryable, so this
            # fixture is a discrimination guard: the recovery ATTEMPT is
            # illegal, independent of whether the underlying error was
            # retryable.
            return ScoreResult(
                passed=False,
                score=0.0,
                reasons=(
                    "recovery_strategy='resume_same_job' attempts an illegal in-place "
                    "FAILED -> PENDING transition on the SAME job (correctly rejected by "
                    "the domain state machine) — the only defined retryable state is a "
                    "NEW job at PENDING, not a resumed one",
                ),
            )
        # transition() did not raise — that itself is the failure: the
        # domain state machine must reject this edge.
        return ScoreResult(
            passed=False,
            score=0.0,
            reasons=(
                "expected transition(FAILED, PENDING) to raise InvalidJobTransitionError, "
                "it did not — the domain state machine no longer protects the terminal "
                "FAILED state",
            ),
        )

    if recovery_strategy == "none":
        if job_error.retryable:
            return ScoreResult(
                passed=False,
                score=0.0,
                reasons=(
                    f"error {job_error.error_code!r} is retryable=True but no recovery was "
                    "attempted at all",
                ),
            )
        return ScoreResult(passed=True, score=1.0, reasons=())

    return ScoreResult(
        passed=False, score=0.0, reasons=(f"unknown recovery_strategy {recovery_strategy!r}",)
    )


__all__ = ["score"]

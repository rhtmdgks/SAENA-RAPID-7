"""Clock-window incomplete restart (w5-20 deliverable 2, bullet 6): workflow
replay mid-window -> timer continues (cross-ref w5-14 integration), asserting
the OUTCOME-LEVEL invariant.

The mechanism-level proof that a `MeasurementWorkflow`'s durable 7-day timer
survives a worker restart mid-window and resumes toward the SAME absolute end
(never reset) is ALREADY exhaustively covered by w5-14's own REAL Temporal
time-skipping suite:

    tests/integration/measurement_workflow/test_measurement_workflow.py::
        test_worker_restart_midwindow_timer_continues_not_reset

This module does not duplicate that Temporal harness (a second, weaker copy
of the same mechanism would not add coverage — see that test's own docstring
for the exact "crash-at-day-3.5" scenario and its replay-determinism
rationale). What THIS module adds, per the mission ("assert the outcome-level
invariant"), is the invariant one layer OUTSIDE the workflow: whatever the
window/clock state was at the moment evaluation happens, `run_measurement`
(the same pure pipeline the workflow's `collect_and_decide` activity calls)
must treat "window not yet complete" (a restart caught mid-window, before the
7-day end) and "window complete" (a restart caught after the 7-day end) as
the ONLY two possible clock-derived outcomes — never a third state, and never
a PASS/FAIL minted from an incomplete window regardless of how many times the
same inputs are (re-)evaluated, which is exactly what "the timer continues"
must mean from the outcome side: re-evaluating before the original end is
always UNDETERMINED(window_incomplete), and re-evaluating after the ORIGINAL
end (not a reset one) is decidable — proven here against REAL Postgres-backed
ports, complementing (not replacing) w5-14's Temporal-level proof.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest
from measurement_failure_factories import make_pg_ports
from pipeline_factories import make_happy_path_inputs, make_policies
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement

pytestmark = pytest.mark.integration


def test_reevaluation_before_window_end_is_undetermined_every_time(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """Simulates a worker restart that re-evaluates measurement state
    mid-window, repeatedly, before the original 7-day end: EVERY evaluation
    is UNDETERMINED(window_incomplete) — the timer never "gives up" and
    grants a premature verdict just because it was asked more than once."""
    inputs, registration = make_happy_path_inputs()
    policies = make_policies(registration)
    ports = make_pg_ports(postgres_url)

    window_anchor = inputs.server_received_at
    mid_window = window_anchor + timedelta(days=3, hours=12)  # Day 3.5 — mid-window

    # SAME run_id across every re-evaluation attempt — a worker restart
    # re-evaluating the SAME in-flight run, not a series of independent runs.
    # Every attempt supplies the identical mid_window `evaluation_at`, so the
    # sealed evidence bundle's entries (and therefore its content-addressed
    # `manifest_hash` — see `evidence.py`'s position-committing chain, which
    # folds in `entries` only, never `run_id`) are byte-identical across
    # attempts; a DIFFERENT run_id per attempt would keep `manifest_hash`
    # identical while changing the top-level manifest dict's `run_id` field,
    # which the content-addressed evidence store correctly refuses as
    # `EvidenceHashMismatchError` (a real hash-collision guard — see
    # `test_at_least_once_replay.py`'s docstring for the full rationale).
    mid_window_inputs = dataclasses.replace(inputs, evaluation_at=mid_window)
    for _attempt in range(3):  # re-evaluated 3x, as a replay-after-restart would
        outcome = run_measurement(mid_window_inputs, ports, policies)
        assert outcome.status is OutcomeStatus.UNDETERMINED
        assert ReasonCode.WINDOW_INCOMPLETE in outcome.reason_codes
        assert outcome.status is not OutcomeStatus.PASS

    # Never "gives up" after repeated asks: exactly one decision is on
    # record (idempotent replay), and it is the SAME honest UNDETERMINED —
    # not upgraded, not duplicated.
    decisions = ports.decision_store.list_decisions(inputs.tenant_id)
    assert len(decisions) == 1
    assert decisions[0].outcome == OutcomeStatus.UNDETERMINED.value


def test_reevaluation_after_original_end_is_decidable_never_stuck_undetermined(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """After the ORIGINAL 7-day end has passed (the timer "continued" to its
    real end rather than being reset by a restart), re-evaluation is
    decidable — WINDOW_INCOMPLETE must NOT still be present. This is the
    outcome-side complement of w5-14's workflow-level proof that the timer
    fires at the original end, not a reset one."""
    inputs, registration = make_happy_path_inputs()
    policies = make_policies(registration)
    ports = make_pg_ports(postgres_url)

    window_anchor = inputs.server_received_at
    after_original_end = window_anchor + timedelta(days=7, hours=1)
    late_inputs = dataclasses.replace(inputs, evaluation_at=after_original_end)

    outcome = run_measurement(late_inputs, ports, policies)

    assert ReasonCode.WINDOW_INCOMPLETE not in outcome.reason_codes
    # A decidable outcome: PASS (qualifying) since make_happy_path_inputs's
    # default fixture is the qualifying happy path.
    assert outcome.status is OutcomeStatus.PASS


def test_window_state_is_derived_from_evaluation_at_not_wall_clock_reads(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """The pipeline's window-completeness decision depends ONLY on the
    caller-supplied `evaluation_at` (Temporal workflow-time in production,
    per `orchestrator.py`'s own docstring) — never `datetime.now()`. Two
    identical inputs differing ONLY in evaluation_at (one before, one after
    the same absolute end) must diverge in EXACTLY the window-completeness
    reason code, proving the decision is a pure function of the supplied
    instant, not of real wall-clock time at test-run time (which would make
    this test flaky/non-deterministic if it were reading the real clock)."""
    inputs, registration = make_happy_path_inputs()
    policies = make_policies(registration)

    window_anchor = inputs.server_received_at
    before_end = dataclasses.replace(
        inputs,
        run_id=inputs.run_id + "-before",
        evaluation_at=window_anchor + timedelta(days=6),
    )
    after_end = dataclasses.replace(
        inputs,
        run_id=inputs.run_id + "-after",
        evaluation_at=window_anchor + timedelta(days=8),
    )

    outcome_before = run_measurement(before_end, make_pg_ports(postgres_url), policies)
    outcome_after = run_measurement(after_end, make_pg_ports(postgres_url), policies)

    assert ReasonCode.WINDOW_INCOMPLETE in outcome_before.reason_codes
    assert ReasonCode.WINDOW_INCOMPLETE not in outcome_after.reason_codes

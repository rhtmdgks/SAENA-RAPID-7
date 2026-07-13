"""REAL Temporal time-skipping integration tests for ``MeasurementWorkflow`` (w5-14).

Runs against ``temporalio.testing.WorkflowEnvironment.start_time_skipping()`` — a
genuine embedded Temporal test-server process (NOT a mock of the client/server),
with a virtual clock the tests advance EXPLICITLY (``env.sleep``) so the 7-day
durable timer is exercised in milliseconds without ANY wall-clock sleep
(wave5-plan.md H6: "Temporal durable timer + time-skipping tests"; task: "NEVER
wall-clock sleep").

Honest-skip discipline (matches ``tests/integration/orchestrator/
test_execution_workflow.py``): a bounded-timeout probe starts the test server in
a module-scoped fixture; if the binary cannot be obtained within the timeout,
EVERY test here is skipped with the concrete startup exception — never a silent
pass.

Payloads are pydantic (``Accepted``), so the client/env uses
``temporalio.contrib.pydantic.pydantic_data_converter`` — the canonical
temporalio path for pydantic workflow payloads.

Time-skipping environment gotchas these tests encode (each observed empirically
against the real test server, not guessed):

1. VIRTUAL-CLOCK ANCHORING — confirmations are anchored at the environment's
   CURRENT virtual time (``env.get_current_time()``), never at a fixed past
   instant: a past anchor makes ``window.end`` already elapsed, the timer
   degenerates to zero, and every "mid-window" scenario becomes vacuous.
2. STICKY-CACHE RESTART DEADLOCK — after a Worker shuts down mid-workflow, the
   server keeps dispatching to the dead Worker's sticky queue; the sticky
   schedule-to-start timeout is virtual-time-based, and virtual time is locked
   while nothing skips — a circular wait that hangs the whole environment.
   ``max_cached_workflows=0`` disables sticky queues entirely, which ALSO forces
   a full-history REPLAY on every single activation — a continuous, stronger
   replay-determinism exercise for every test in this module.
3. RESULT-AWAIT MEGA-SKIP — awaiting ``handle.result()`` with auto time
   skipping can overshoot the shared virtual clock by ~10 YEARS (to the default
   workflow execution timeout) once the workflow has completed, poisoning every
   later test's clock assumptions. These tests therefore NEVER rely on
   result-await auto-skipping: the clock is advanced only by exact ``env.sleep``
   calls (RUNNING asserted just before the window end, COMPLETED just after —
   which is also a sharper timer assertion), and results are fetched only under
   ``env.auto_time_skipping_disabled()`` (a SYNC context manager).

Scenarios (task deliverable 3):
- full flow: signal -> window -> 7-day skip -> DECIDED outcome
- replay determinism: worker restart mid-window (crash-at-day-3.5) — timer
  continues to the SAME absolute end, NOT reset
- duplicate signal idempotent (timer not restarted)
- abort path (UNDETERMINED aborted)
- Day-2-late path (no timer, UNDETERMINED deployment_late)
- conflicting confirmation (first wins, original window continues)
- timezone-independence (anchor instants at a DST boundary)
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone

import pytest
from attribution_factories import (
    OTHER_REGISTRATION_HASH,
    REGISTRATION_HASH,
    RUN_ID,
    make_accepted,
)
from saena_domain.measurement.confirmation import Accepted
from saena_experiment_attribution.workflow.activities import (
    collect_and_decide_fixture_activity,
    derive_window,
)
from saena_experiment_attribution.workflow.workflow import (
    ABORT_MEASUREMENT_SIGNAL_NAME,
    DEPLOYMENT_CONFIRMED_SIGNAL_NAME,
    PAUSE_OBSERVATION_SIGNAL_NAME,
    RESUME_SIGNAL_NAME,
    MeasurementWorkflow,
    MeasurementWorkflowInput,
)
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

pytestmark = pytest.mark.integration

_STARTUP_TIMEOUT_SECONDS = 30
_TASK_QUEUE = "measurement-workflow-integration-queue"

_SEVEN_DAYS = timedelta(days=7)
#: Margin used to straddle the window end: RUNNING is asserted at end - margin,
#: COMPLETED at end + margin.
_MARGIN = timedelta(hours=1)


# --------------------------------------------------------------------------- #
# Honest-skip probe (orchestrator pattern)
# --------------------------------------------------------------------------- #
async def _try_start_environment() -> WorkflowEnvironment | Exception:
    try:
        return await asyncio.wait_for(
            WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter),
            timeout=_STARTUP_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - probe: capture ANY startup failure to skip on
        return exc


@pytest.fixture(scope="module")
def _probe_result() -> WorkflowEnvironment | Exception:
    return asyncio.run(_try_start_environment())


@pytest.fixture
def temporal_env(
    _probe_result: WorkflowEnvironment | Exception,
) -> WorkflowEnvironment:
    if isinstance(_probe_result, Exception):
        pytest.skip(
            "temporalio time-skipping test server unavailable "
            f"(startup failed within {_STARTUP_TIMEOUT_SECONDS}s): "
            f"{type(_probe_result).__name__}: {_probe_result}"
        )
    return _probe_result


@pytest.fixture(scope="module", autouse=True)
def _shutdown_environment_after_module(
    _probe_result: WorkflowEnvironment | Exception,
) -> Iterator[None]:
    yield
    if not isinstance(_probe_result, Exception):
        asyncio.run(_probe_result.shutdown())


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _worker(client: Client) -> Worker:
    """A Worker registering the workflow + both activities (derive_window and
    the fixture collect-and-decide, shipped as a TYPED ``@activity.defn`` under
    the stable ``collect_and_decide`` name).

    ``max_cached_workflows=0``: disables the workflow cache/sticky queue —
    required for the worker-restart test (module docstring gotcha #2) and a
    deliberate hardening everywhere else: every activation replays the ENTIRE
    workflow history from scratch, so any nondeterminism in the workflow body
    fails loudly in every test here, not just the restart one.
    """
    return Worker(
        client,
        task_queue=_TASK_QUEUE,
        workflows=[MeasurementWorkflow],
        activities=[derive_window, collect_and_decide_fixture_activity],
        max_cached_workflows=0,
    )


def _input(registration_hash: str = REGISTRATION_HASH) -> MeasurementWorkflowInput:
    return MeasurementWorkflowInput(expected_registration_hash=registration_hash, run_id=RUN_ID)


async def _env_now(env: WorkflowEnvironment) -> datetime:
    now = await env.get_current_time()
    return now.replace(tzinfo=UTC) if now.tzinfo is None else now


async def _accepted_at_env_now(
    env: WorkflowEnvironment,
    *,
    idempotency_key: str,
    deployed_commit_sha: str = "commit-abc123",
    approved_delta: timedelta = timedelta(0),
) -> tuple[Accepted, datetime]:
    """Build an ``Accepted`` anchored at the environment's CURRENT virtual time
    (module docstring gotcha #1). ``approved_delta`` shifts the registration's
    ``approved_at`` relative to the anchor (e.g. ``-3 days`` to construct a
    Day-2-late deployment). Returns ``(accepted, anchor)``."""
    anchor = await _env_now(env)
    accepted = make_accepted(
        idempotency_key=idempotency_key,
        deployed_commit_sha=deployed_commit_sha,
        server_received_at=anchor,
        approved_at=anchor + approved_delta,
    )
    return accepted, anchor


async def _fetch_completed_result(env: WorkflowEnvironment, handle: WorkflowHandle):  # noqa: ANN202
    """Fetch the result of an already-completed workflow WITHOUT unlocking time
    skipping (module docstring gotcha #3): the shared virtual clock must not
    move just because a result is read."""
    with env.auto_time_skipping_disabled():
        return await handle.result()


async def _assert_running(handle: WorkflowHandle) -> None:
    desc = await handle.describe()
    assert desc.status == WorkflowExecutionStatus.RUNNING


async def _assert_completed(handle: WorkflowHandle, message: str) -> None:
    desc = await handle.describe()
    assert desc.status == WorkflowExecutionStatus.COMPLETED, message


# --------------------------------------------------------------------------- #
# 1. Full flow: signal -> window -> 7-day skip -> DECIDED outcome
# --------------------------------------------------------------------------- #
def test_full_flow_signal_window_skip_to_decided_outcome(
    temporal_env: WorkflowEnvironment,
) -> None:
    async def scenario() -> None:
        async with _worker(temporal_env.client):
            accepted, anchor = await _accepted_at_env_now(temporal_env, idempotency_key="idem-full")
            handle = await temporal_env.client.start_workflow(
                MeasurementWorkflow.run,
                _input(),
                id="wf-mw-full-flow",
                task_queue=_TASK_QUEUE,
            )
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, accepted)
            status = await handle.query(MeasurementWorkflow.status)
            assert status.window_bound is True

            # Advance the virtual clock to just BEFORE the window end: the
            # timer must NOT have fired early.
            await temporal_env.sleep(_SEVEN_DAYS - _MARGIN)
            await _assert_running(handle)

            # Cross the window end: the durable timer fires, collect-and-decide
            # runs, the workflow completes — a REAL 7-day skip, zero wall-clock.
            await temporal_env.sleep(2 * _MARGIN)
            await _assert_completed(handle, "timer did not fire after the 7-day window end")

            result = await _fetch_completed_result(temporal_env, handle)
            assert result.status.value == "decided"
            assert result.outcome_ref == "outcome-ref:idem-full"
            assert result.reason is None
            # The clock advanced by exactly the explicit skips (7d + margin),
            # give or take real milliseconds of RPC drift — pinning that a REAL
            # ~7-day virtual skip happened, with no unbounded overshoot.
            now = await _env_now(temporal_env)
            assert anchor + _SEVEN_DAYS <= now < anchor + _SEVEN_DAYS + timedelta(hours=2)

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 2. Replay determinism — worker restart mid-window (crash-at-day-3.5)
# --------------------------------------------------------------------------- #
def test_worker_restart_midwindow_timer_continues_not_reset(
    temporal_env: WorkflowEnvironment,
) -> None:
    """The load-bearing replay-safety test: bring the Worker down at ~Day 3.5
    (mid-window), bring a FRESH Worker up, advance the virtual clock to just
    past the ORIGINAL Day-7 end, and confirm the workflow COMPLETED — i.e. the
    durable timer resumed toward the SAME absolute end after full-history
    replay. A timer that had been RESET by the restart (a fresh 7 days from Day
    3.5 → end at Day 10.5) would still be RUNNING at Day 7+1h, failing the
    completed assertion.
    """

    async def scenario() -> None:
        # --- First Worker: start the workflow, deliver the signal, advance to
        # ~Day 3.5, and shut the Worker DOWN (simulated crash mid-window)
        # WITHOUT the workflow completing.
        async with _worker(temporal_env.client):
            accepted, _anchor = await _accepted_at_env_now(
                temporal_env, idempotency_key="idem-replay"
            )
            handle = await temporal_env.client.start_workflow(
                MeasurementWorkflow.run,
                _input(),
                id="wf-mw-replay",
                task_queue=_TASK_QUEUE,
            )
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, accepted)
            status = await handle.query(MeasurementWorkflow.status)
            assert status.window_bound is True
            # Advance the virtual clock to Day 3.5 — mid-window.
            await temporal_env.sleep(timedelta(days=3, hours=12))
            await _assert_running(handle)
        # Worker DOWN — the durable timer persists server-side; nothing polls.

        # --- Fresh Worker: the workflow replays its full history (cache is
        # disabled) and the timer continues toward the SAME absolute end.
        async with _worker(temporal_env.client):
            # Advance to Day 7 - 1h: STILL before the original end — the
            # restart must not have fired anything early.
            await temporal_env.sleep(timedelta(days=3, hours=11))
            await _assert_running(handle)

            # Cross the ORIGINAL Day-7 end (Day 7 + 1h). A reset timer would
            # end at Day 10.5 and still be running here.
            await temporal_env.sleep(2 * _MARGIN)
            await _assert_completed(
                handle,
                "workflow still running at Day 7+1h after a mid-window worker "
                "restart — the durable timer appears to have RESET instead of "
                "continuing to its original absolute end",
            )

            result = await _fetch_completed_result(temporal_env, handle)
            assert result.status.value == "decided"
            assert result.outcome_ref == "outcome-ref:idem-replay"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 3. Duplicate signal idempotent — timer NOT restarted
# --------------------------------------------------------------------------- #
def test_duplicate_deployment_signal_is_idempotent_no_restart(
    temporal_env: WorkflowEnvironment,
) -> None:
    async def scenario() -> None:
        async with _worker(temporal_env.client):
            accepted, _anchor = await _accepted_at_env_now(temporal_env, idempotency_key="idem-dup")
            handle = await temporal_env.client.start_workflow(
                MeasurementWorkflow.run,
                _input(),
                id="wf-mw-duplicate",
                task_queue=_TASK_QUEUE,
            )
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, accepted)
            status = await handle.query(MeasurementWorkflow.status)
            assert status.window_bound is True

            # Advance to Day 3 mid-window, then RE-DELIVER the byte-identical
            # signal (at-least-once redelivery). Idempotent no-op — the timer
            # must NOT restart.
            await temporal_env.sleep(timedelta(days=3))
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, accepted)
            status = await handle.query(MeasurementWorkflow.status)
            assert status.window_bound is True
            assert status.conflicting_replays == 0  # duplicate != conflict

            # Just before the ORIGINAL Day-7 end: still running.
            await temporal_env.sleep(timedelta(days=4) - _MARGIN)
            await _assert_running(handle)
            # Just after the ORIGINAL end: completed. A RESTARTED timer would
            # end at Day 3+7=10 and still be running here.
            await temporal_env.sleep(2 * _MARGIN)
            await _assert_completed(
                handle,
                "workflow still running just after the ORIGINAL window end — "
                "the duplicate signal appears to have RESTARTED the timer",
            )

            result = await _fetch_completed_result(temporal_env, handle)
            assert result.status.value == "decided"
            assert result.outcome_ref == "outcome-ref:idem-dup"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 4. Abort path — UNDETERMINED(aborted), never silently dropped
# --------------------------------------------------------------------------- #
def test_abort_midwindow_yields_undetermined_aborted(
    temporal_env: WorkflowEnvironment,
) -> None:
    async def scenario() -> None:
        async with _worker(temporal_env.client):
            accepted, anchor = await _accepted_at_env_now(
                temporal_env, idempotency_key="idem-abort"
            )
            handle = await temporal_env.client.start_workflow(
                MeasurementWorkflow.run,
                _input(),
                id="wf-mw-abort",
                task_queue=_TASK_QUEUE,
            )
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, accepted)
            status = await handle.query(MeasurementWorkflow.status)
            assert status.window_bound is True

            # Day 2, mid-window: abort. The workflow must complete UNDETERMINED
            # promptly — no waiting out the timer, never silently dropped.
            await temporal_env.sleep(timedelta(days=2))
            await handle.signal(ABORT_MEASUREMENT_SIGNAL_NAME)
            # Completion needs NO virtual-time advance (signal processing only,
            # real milliseconds) — fetched under disabled skipping (gotcha #3).
            result = await _fetch_completed_result(temporal_env, handle)
            assert result.status.value == "undetermined_aborted"
            assert result.reason == "aborted"
            assert result.outcome_ref is None
            # The clock sits at ~Day 2 (abort time) — the Day-7 end never came;
            # the abort genuinely interrupted the timer.
            now = await _env_now(temporal_env)
            assert now < anchor + _SEVEN_DAYS

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 5. Day-2-late path — clock never starts, UNDETERMINED(deployment_late)
# --------------------------------------------------------------------------- #
def test_day2_late_deployment_never_starts_timer(
    temporal_env: WorkflowEnvironment,
) -> None:
    async def scenario() -> None:
        async with _worker(temporal_env.client):
            # Registration approved 3 days BEFORE the confirmation anchor —
            # past the Day-2 deadline. start_measurement_window (in the
            # derive_window activity) returns Undetermined(deployment_late);
            # the workflow completes WITHOUT ever starting a timer.
            accepted, anchor = await _accepted_at_env_now(
                temporal_env,
                idempotency_key="idem-late",
                approved_delta=timedelta(days=-3),
            )
            handle = await temporal_env.client.start_workflow(
                MeasurementWorkflow.run,
                _input(),
                id="wf-mw-late",
                task_queue=_TASK_QUEUE,
            )
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, accepted)
            # Completes with NO virtual-time advance at all — no timer was ever
            # started (§7.3:483).
            result = await _fetch_completed_result(temporal_env, handle)
            assert result.status.value == "undetermined_deployment_late"
            assert result.reason == "deployment_late"
            assert result.outcome_ref is None
            # Virtual clock unmoved (completion consumed zero virtual time).
            now = await _env_now(temporal_env)
            assert now < anchor + timedelta(days=1)

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 6. Conflicting confirmation — first wins, original window continues
# --------------------------------------------------------------------------- #
def test_conflicting_confirmation_records_replay_and_keeps_original_window(
    temporal_env: WorkflowEnvironment,
) -> None:
    async def scenario() -> None:
        async with _worker(temporal_env.client):
            first, _anchor = await _accepted_at_env_now(
                temporal_env, idempotency_key="idem-conflict", deployed_commit_sha="c1"
            )
            handle = await temporal_env.client.start_workflow(
                MeasurementWorkflow.run,
                _input(),
                id="wf-mw-conflict",
                task_queue=_TASK_QUEUE,
            )
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, first)
            status = await handle.query(MeasurementWorkflow.status)
            assert status.window_bound is True

            # Day 1: a conflicting confirmation — same idempotency key,
            # DIFFERENT content (different commit), LATER anchor that would
            # move the window end to Day 8 if (wrongly) accepted.
            await temporal_env.sleep(timedelta(days=1))
            conflicting, _ = await _accepted_at_env_now(
                temporal_env, idempotency_key="idem-conflict", deployed_commit_sha="c2"
            )
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, conflicting)
            status = await handle.query(MeasurementWorkflow.status)
            # Recorded, never silently dropped; original binding retained.
            assert status.conflicting_replays == 1

            # Just before the FIRST window's Day-7 end: still running.
            await temporal_env.sleep(timedelta(days=6) - _MARGIN)
            await _assert_running(handle)
            # Just after the FIRST window's end: completed — the conflicting
            # confirmation did NOT move the end to Day 8 (first wins).
            await temporal_env.sleep(2 * _MARGIN)
            await _assert_completed(
                handle,
                "workflow still running just after the FIRST window's end — "
                "the conflicting confirmation appears to have re-anchored the "
                "window (first-wins violated)",
            )

            result = await _fetch_completed_result(temporal_env, handle)
            assert result.status.value == "decided"
            # Decided against the FIRST confirmation's key (first wins).
            assert result.outcome_ref == "outcome-ref:idem-conflict"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 6b. Pause/resume — a decision is NEVER taken while observation is paused
# --------------------------------------------------------------------------- #
def test_pause_holds_decision_past_window_end_until_resume(
    temporal_env: WorkflowEnvironment,
) -> None:
    """The load-bearing pause invariant: if ``pause_observation`` is in effect
    when the durable 7-day timer fires, the workflow must NOT take a decision —
    it holds at the collect-and-decide gate (``run()`` step 4) even as the
    virtual clock runs WELL past the original absolute window end. Only
    ``resume`` releases it, and the outcome is anchored to the ORIGINAL window
    (pause never moved the end nor restarted anything).
    """

    async def scenario() -> None:
        async with _worker(temporal_env.client):
            accepted, _anchor = await _accepted_at_env_now(
                temporal_env, idempotency_key="idem-pause"
            )
            handle = await temporal_env.client.start_workflow(
                MeasurementWorkflow.run,
                _input(),
                id="wf-mw-pause",
                task_queue=_TASK_QUEUE,
            )
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, accepted)
            status = await handle.query(MeasurementWorkflow.status)
            assert status.window_bound is True

            # Just before the Day-7 end: pause observation (still mid-window).
            await temporal_env.sleep(_SEVEN_DAYS - _MARGIN)
            await handle.signal(PAUSE_OBSERVATION_SIGNAL_NAME)
            status = await handle.query(MeasurementWorkflow.status)
            assert status.paused is True

            # Advance WELL PAST the original absolute end (to ~Day 21 — three
            # windows' worth). The durable timer has fired, but because
            # observation is PAUSED the workflow must NOT decide: it holds at
            # the pause gate, still RUNNING, no collect-and-decide taken.
            await temporal_env.sleep(timedelta(days=14) + 2 * _MARGIN)
            await _assert_running(handle)
            status = await handle.query(MeasurementWorkflow.status)
            # Still paused, still bound, no outcome — a decision was NOT taken
            # while paused (the load-bearing invariant).
            assert status.paused is True
            assert status.window_bound is True

            # Resume: NOW the held decision is released — the workflow completes
            # and DECIDES, anchored to the ORIGINAL window (pause moved nothing).
            await handle.signal(RESUME_SIGNAL_NAME)
            result = await _fetch_completed_result(temporal_env, handle)
            assert result.status.value == "decided"
            assert result.outcome_ref == "outcome-ref:idem-pause"
            assert result.reason is None

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 7. Timezone-independence — anchor instants at a DST boundary
# --------------------------------------------------------------------------- #
def test_timezone_independence_anchor_at_dst_boundary(
    temporal_env: WorkflowEnvironment,
) -> None:
    """The SAME physical instant expressed in different UTC offsets (at the US
    fall-back DST boundary) yields the SAME window end — the arithmetic is on
    absolute aware instants (clock.py), never wall-clock calendar fields. Two
    workflows whose anchors are the identical instant written as UTC vs. a
    -04:00 (EDT) offset must BOTH be running just before the shared end and
    BOTH be completed just after it. The boundary instant is chosen in the
    virtual clock's FUTURE (gotcha #1) so both timers are real.
    """
    # 2026-11-01 06:00Z is 02:00 EDT — the US fall-back instant (EDT->EST).
    # Express the identical physical instant two ways.
    instant_utc = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    instant_offset = datetime(2026, 11, 1, 2, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert instant_utc == instant_offset  # same physical instant

    async def scenario() -> None:
        async with _worker(temporal_env.client):
            # Guard: the boundary must still be in the virtual clock's future
            # (gotcha #1). The clock starts at ~real now (2026-07) and every
            # prior test advances it by mere days (all skips here are explicit
            # and exact — gotcha #3 discipline), so 2026-11-01 stays ahead.
            now = await _env_now(temporal_env)
            assert now < instant_utc, "DST fixture instant is no longer in the virtual future"

            # Start BOTH workflows and deliver BOTH signals up front — the two
            # timers share ONE absolute end instant (instant + 7d).
            handles: list[WorkflowHandle] = []
            for idx, instant in enumerate((instant_utc, instant_offset)):
                accepted = make_accepted(
                    idempotency_key=f"idem-dst-{idx}",
                    server_received_at=instant,
                    approved_at=instant,
                )
                handle = await temporal_env.client.start_workflow(
                    MeasurementWorkflow.run,
                    _input(),
                    id=f"wf-mw-dst-{idx}",
                    task_queue=_TASK_QUEUE,
                )
                await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, accepted)
                handles.append(handle)

            shared_end = instant_utc + _SEVEN_DAYS
            # Just before the shared end (spanning the DST fall-back): BOTH
            # still running — neither offset notation shortened its window.
            await temporal_env.sleep((shared_end - _MARGIN) - now)
            for handle in handles:
                await _assert_running(handle)
            # Just after the shared end: BOTH completed at the SAME absolute
            # instant — instant arithmetic, DST-proof.
            await temporal_env.sleep(2 * _MARGIN)
            for handle in handles:
                await _assert_completed(
                    handle,
                    "a DST-offset-notated anchor produced a different window "
                    "end than the identical UTC instant",
                )

            for idx, handle in enumerate(handles):
                result = await _fetch_completed_result(temporal_env, handle)
                assert result.status.value == "decided"
                assert result.outcome_ref == f"outcome-ref:idem-dst-{idx}"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 8. Structural refusal — a confirmation for a DIFFERENT registration
# --------------------------------------------------------------------------- #
def test_confirmation_for_wrong_registration_is_refused_never_binds(
    temporal_env: WorkflowEnvironment,
) -> None:
    """A confirmation whose embedded registration hash != the run's expected
    hash is structurally refused — it never binds a window, so the workflow
    stays RUNNING (defense-in-depth over the already-Accepted payload)."""

    async def scenario() -> None:
        async with _worker(temporal_env.client):
            anchor = await _env_now(temporal_env)
            wrong = make_accepted(
                idempotency_key="idem-wrong-reg",
                server_received_at=anchor,
                approved_at=anchor,
                registration_hash=OTHER_REGISTRATION_HASH,
            )
            handle = await temporal_env.client.start_workflow(
                MeasurementWorkflow.run,
                _input(REGISTRATION_HASH),
                id="wf-mw-wrong-reg",
                task_queue=_TASK_QUEUE,
            )
            await handle.signal(DEPLOYMENT_CONFIRMED_SIGNAL_NAME, wrong)
            status = await handle.query(MeasurementWorkflow.status)
            assert status.window_bound is False
            await _assert_running(handle)

    asyncio.run(scenario())

"""``MeasurementWorkflow`` — the durable 7-day measurement Temporal workflow (w5-14).

CRITICAL (task boundary): this is the ONLY Temporal workflow definition for
``experiment-attribution-service``. It lives here, inside the service's
``src/saena_experiment_attribution/workflow/`` package, NOT under the root
``workflows/**`` directory (that root path is PROTECTED — CLAUDE.md protected
paths — and is not a Temporal-workflow-code directory in this repo's layout;
same placement rationale as ``saena_orchestrator.workflow``).

## Shape (mirrors the orchestrator precedent)

Pure decision logic lives in ``workflow_logic`` (import-safe, unit-tested to
~100% off-server); THIS shell is the ``@workflow.defn`` that drives real
Temporal time. The shell contains no business arithmetic — it delegates every
classification to the pure core and every nondeterministic-adjacent domain call
(window derivation, collect-and-decide) to an ACTIVITY.

## Authority path (ADR-0003, wave5-plan.md)

The workflow starts and awaits a DIRECT ``deployment_confirmed`` signal (the
signal is authoritative; the ``deployment.confirmed.v1`` bus event is
notification-only). The signal payload is an ALREADY-VALIDATED ``Accepted``
confirmation reference — validation happened upstream (policy-gate/service,
w5-03). The workflow RE-CHECKS structural invariants defensively
(``classify_confirmation_signal``) but never re-runs trust verification.

## Durable timer (single timer, NO polling loop)

On the first accepted confirmation the workflow schedules ``derive_window``:
- ``deployment_late`` → complete with ``UNDETERMINED(deployment_late)``; the
  7-day timer is NEVER started (§7.3:483).
- otherwise → a SINGLE durable wait until ``window.end`` via
  ``workflow.wait_condition(lambda: aborted, timeout=remaining)``. ``remaining``
  is computed from ``workflow.now()`` to the frozen absolute ``window.end`` — so
  on a worker crash/restart mid-window the timer CONTINUES to the same absolute
  end (replay-safe; NOT reset — the crash-at-day-3.5 integration test pins
  this). There is no polling loop; exactly one durable timer.

## Signals

- ``deployment_confirmed`` — first → start; duplicate (same key+fingerprint) →
  idempotent no-op, timer NOT restarted; conflicting (same key, different
  content) → record ``conflicting_replay``, ORIGINAL window continues
  (fail-closed, first wins).
- ``pause_observation`` / ``resume`` — toggle the observation-pause flag. The
  ABSOLUTE 7-day window end does NOT move (the external-performance clock is a
  causality contract on wall-time, not on observation activity); pause governs
  whether the collect-and-decide step may run — at timer fire the workflow waits
  for ``resume`` before deciding, so a decision is never taken while paused.
- ``abort_measurement`` — record ``UNDETERMINED(aborted)`` and complete; never
  silently dropped.

At timer fire (and not paused, not aborted) the workflow schedules
``collect_and_decide`` (by name) and returns the ``DECIDED`` outcome reference.
"""

from __future__ import annotations

import contextlib
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from dataclasses import dataclass

    from saena_domain.measurement.confirmation import Accepted

    from saena_experiment_attribution.workflow.activities import (
        COLLECT_AND_DECIDE_ACTIVITY,
        CollectAndDecideInput,
        CollectAndDecideResult,
        DeriveWindowInput,
        DeriveWindowResult,
        derive_window,
    )
    from saena_experiment_attribution.workflow.timeouts import (
        ACTIVITY_START_TO_CLOSE_TIMEOUT,
        HEARTBEAT_TIMEOUT,
    )
    from saena_experiment_attribution.workflow.workflow_logic import (
        DEPLOYMENT_CONFIRMED_SIGNAL,
        MeasurementOutcome,
        SignalDisposition,
        WindowBinding,
        aborted_outcome,
        classify_confirmation_signal,
        decided_outcome,
        deployment_late_outcome,
        extract_binding,
    )

# Signal names re-exported at module scope so a caller/test imports them from
# ONE place (same discipline as saena_orchestrator's APPROVE_SIGNAL_NAME).
DEPLOYMENT_CONFIRMED_SIGNAL_NAME = DEPLOYMENT_CONFIRMED_SIGNAL
PAUSE_OBSERVATION_SIGNAL_NAME = "pause_observation"
RESUME_SIGNAL_NAME = "resume"
ABORT_MEASUREMENT_SIGNAL_NAME = "abort_measurement"

# Derive-window activity is a fast pure domain call — a short, bounded timeout
# (NOT the 7200s runner bound; that is the orchestrator's runner-Job concern).
_DERIVE_WINDOW_START_TO_CLOSE = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class MeasurementWorkflowInput:
    """Workflow start payload — the registered run this instance governs.

    ``expected_registration_hash`` binds the run to a specific pre-registered
    experiment; every confirmation signal is structurally re-checked against it
    (a confirmation for a different registration can never re-anchor this run).
    ``run_id`` is the run identity (used as the recorded key if an abort arrives
    before any window is bound).
    """

    expected_registration_hash: str
    run_id: str


@dataclass(frozen=True, slots=True)
class MeasurementWorkflowStatus:
    """Point-in-time projection returned by the ``status`` query."""

    window_bound: bool
    paused: bool
    aborted: bool
    conflicting_replays: int
    window_days: int | None


@workflow.defn
class MeasurementWorkflow:
    """Durable 7-day measurement window governed by a direct confirmation signal.

    One workflow instance == one measurement run for one registered experiment.
    ``expected_registration_hash`` (the run's bound registration) is fixed at
    start; every confirmation signal is structurally re-checked against it.
    """

    def __init__(self) -> None:
        self._expected_registration_hash: str | None = None
        # First-wins window binding (None until the first accepted confirmation).
        self._binding: WindowBinding | None = None
        # The Accepted from the START signal — held so run() can build the
        # derive_window activity input (mirrors the orchestrator keeping
        # activity scheduling in run() where the payload is available).
        self._pending_accepted: Accepted | None = None
        # The frozen absolute window end (None until derive_window succeeds).
        self._window_days: int | None = None
        # Terminal / control flags.
        self._aborted = False
        self._paused = False
        # Recorded (non-fatal) conflicting-replay count for observability.
        self._conflicting_replays = 0

    @workflow.run
    async def run(self, workflow_input: MeasurementWorkflowInput) -> MeasurementOutcome:
        self._expected_registration_hash = workflow_input.expected_registration_hash

        # 1. Wait for the FIRST accepted deployment-confirmed signal (or an
        #    abort before any confirmation arrives). The binding is set by the
        #    signal handler on the first START disposition.
        await workflow.wait_condition(lambda: self._binding is not None or self._aborted)
        if self._aborted:
            # Aborted before any window was bound — still recorded, never
            # silently dropped.
            key = self._binding.idempotency_key if self._binding else workflow_input.run_id
            return aborted_outcome(key)

        assert self._binding is not None  # narrowed by wait_condition above
        assert self._pending_accepted is not None
        binding = self._binding

        # 2. Derive the window in an activity (domain call + registration_view
        #    lookup — kept out of the deterministic body). The activity holds
        #    the accepted confirmation the START signal carried.
        derive_result: DeriveWindowResult = await workflow.execute_activity(
            derive_window,
            DeriveWindowInput(accepted=self._pending_accepted),
            start_to_close_timeout=_DERIVE_WINDOW_START_TO_CLOSE,
        )

        if derive_result.deployment_late or derive_result.window is None:
            # Day-2-late → complete UNDETERMINED(deployment_late); NEVER start
            # the timer (§7.3:483).
            return deployment_late_outcome(binding.idempotency_key)

        window = derive_result.window
        self._window_days = window.window_days

        # 3. SINGLE durable timer: wait until the frozen absolute window end,
        #    interruptible by abort. `remaining` is measured from the (durable,
        #    replay-safe) `workflow.now()` to the absolute `window.end`, so a
        #    worker crash/restart mid-window resumes waiting toward the SAME
        #    end instant — the timer continues, never resets. No polling loop.
        remaining = window.end - workflow.now()
        if remaining > timedelta(0):
            # wait_condition returns True if aborted; raises TimeoutError when
            # the window elapses without an abort (the normal completion path).
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self._aborted, timeout=remaining)

        if self._aborted:
            return aborted_outcome(binding.idempotency_key)

        # 4. If paused at fire time, wait for resume before deciding (a decision
        #    is never taken while observation is paused). Abort still wins.
        await workflow.wait_condition(lambda: not self._paused or self._aborted)
        if self._aborted:
            return aborted_outcome(binding.idempotency_key)

        # 5. Timer fired: schedule collect-and-decide (by NAME so w5-13's real
        #    pipeline drops in behind this signature) and return the DECIDED
        #    outcome reference. A by-name call carries no signature for the
        #    payload converter, so `result_type` is passed explicitly — without
        #    it the result arrives as a raw dict, not a CollectAndDecideResult.
        decide_result: CollectAndDecideResult = await workflow.execute_activity(
            COLLECT_AND_DECIDE_ACTIVITY,
            CollectAndDecideInput(
                idempotency_key=binding.idempotency_key,
                content_fingerprint=binding.content_fingerprint,
            ),
            result_type=CollectAndDecideResult,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
        )
        return decided_outcome(binding.idempotency_key, decide_result.outcome_ref)

    @workflow.signal(name=DEPLOYMENT_CONFIRMED_SIGNAL)
    def deployment_confirmed(self, accepted: Accepted) -> None:
        """Direct deployment-confirmed signal (ADR-0003; bus event notification-
        only). Payload = already-validated ``Accepted`` reference; this handler
        RE-CHECKS structural invariants only (``classify_confirmation_signal``).

        - First valid → bind the window (first-wins). Timer start is ``run()``'s
          job (it observes ``_binding`` via ``wait_condition``).
        - Duplicate (same key+fingerprint) → idempotent no-op; the timer is NOT
          restarted (``run()`` never re-observes a binding change).
        - Conflicting (same key, different content) → record ``conflicting_replay``
          and keep the ORIGINAL binding (fail-closed, first wins).
        - Structurally refused (not Accepted, or registration mismatch) → no-op.
        """
        disposition = classify_confirmation_signal(
            accepted,
            self._binding,
            self._expected_registration_hash or "",
        )
        if disposition is SignalDisposition.START:
            self._pending_accepted = accepted
            self._binding = extract_binding(accepted)
        elif disposition is SignalDisposition.CONFLICTING_REPLAY:
            # Recorded, never silently dropped; ORIGINAL window continues.
            self._conflicting_replays += 1
        # DUPLICATE and REFUSED_STRUCTURAL are no-ops (idempotent / rejected).

    @workflow.signal(name=PAUSE_OBSERVATION_SIGNAL_NAME)
    def pause_observation(self) -> None:
        """Pause observation. Does NOT move the absolute window end — the 7-day
        external clock is a wall-time causality contract; pause only gates the
        collect-and-decide step (see ``run()`` step 4)."""
        self._paused = True

    @workflow.signal(name=RESUME_SIGNAL_NAME)
    def resume(self) -> None:
        """Resume observation (clears the pause flag)."""
        self._paused = False

    @workflow.signal(name=ABORT_MEASUREMENT_SIGNAL_NAME)
    def abort_measurement(self) -> None:
        """Abort the measurement. Recorded as ``UNDETERMINED(aborted)`` by
        ``run()`` — never silently dropped. Wins over pause and over a pending
        timer."""
        self._aborted = True

    @workflow.query
    def status(self) -> MeasurementWorkflowStatus:
        """Point-in-time observability without waiting for ``run()`` to return —
        lets a test/caller see whether the window is bound, paused, aborted, and
        how many conflicting replays were recorded (first-wins evidence)."""
        return MeasurementWorkflowStatus(
            window_bound=self._binding is not None,
            paused=self._paused,
            aborted=self._aborted,
            conflicting_replays=self._conflicting_replays,
            window_days=self._window_days,
        )


__all__ = [
    "ABORT_MEASUREMENT_SIGNAL_NAME",
    "DEPLOYMENT_CONFIRMED_SIGNAL_NAME",
    "PAUSE_OBSERVATION_SIGNAL_NAME",
    "RESUME_SIGNAL_NAME",
    "MeasurementWorkflow",
    "MeasurementWorkflowInput",
    "MeasurementWorkflowStatus",
]

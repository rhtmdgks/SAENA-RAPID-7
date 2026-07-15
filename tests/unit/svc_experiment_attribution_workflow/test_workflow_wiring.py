"""``MeasurementWorkflow`` module surface — importable/definable WITHOUT a
Temporal server (mirrors ``tests/unit/svc_orchestrator/test_workflow_wiring.py``).
The actual signal->window->timer->outcome behavior under a live Worker is proven
in ``tests/integration/measurement_workflow/``.
"""

from __future__ import annotations

import temporalio.workflow as w
from attribution_factories import make_accepted
from saena_experiment_attribution.workflow.workflow import (
    ABORT_MEASUREMENT_SIGNAL_NAME,
    DEPLOYMENT_CONFIRMED_SIGNAL_NAME,
    PAUSE_OBSERVATION_SIGNAL_NAME,
    RESUME_SIGNAL_NAME,
    MeasurementWorkflow,
    MeasurementWorkflowInput,
    MeasurementWorkflowStatus,
)
from saena_experiment_attribution.workflow.workflow_logic import (
    DEPLOYMENT_CONFIRMED_SIGNAL,
    MeasurementOutcomeStatus,
)


def test_measurement_workflow_is_a_temporal_workflow_definition() -> None:
    defn = w._Definition.from_class(MeasurementWorkflow)  # noqa: SLF001
    assert defn is not None
    assert defn.name == "MeasurementWorkflow"
    # All four signals + the status query this unit implements.
    assert "deployment_confirmed" in defn.signals
    assert "pause_observation" in defn.signals
    assert "resume" in defn.signals
    assert "abort_measurement" in defn.signals
    assert "status" in defn.queries


def test_signal_name_constants_match_registered_signals() -> None:
    # The workflow-shell re-export and the pure-core constant must agree, and
    # both must match the actual registered signal name — a rename can never
    # silently desync sender and receiver.
    assert DEPLOYMENT_CONFIRMED_SIGNAL_NAME == DEPLOYMENT_CONFIRMED_SIGNAL == "deployment_confirmed"
    assert PAUSE_OBSERVATION_SIGNAL_NAME == "pause_observation"
    assert RESUME_SIGNAL_NAME == "resume"
    assert ABORT_MEASUREMENT_SIGNAL_NAME == "abort_measurement"


def test_workflow_input_is_a_plain_serializable_dataclass() -> None:
    payload = MeasurementWorkflowInput(
        expected_registration_hash="sha256:" + "a" * 64, run_id="run-1"
    )
    assert payload.expected_registration_hash.startswith("sha256:")
    assert payload.run_id == "run-1"


def test_workflow_status_projection_shape() -> None:
    status = MeasurementWorkflowStatus(
        window_bound=True,
        paused=False,
        aborted=False,
        conflicting_replays=2,
        window_days=7,
    )
    assert status.window_bound is True
    assert status.conflicting_replays == 2
    assert status.window_days == 7


def test_fresh_workflow_instance_starts_unbound_and_unpaused() -> None:
    # The __init__ defaults are the fail-safe starting state: no window bound,
    # not paused, not aborted, no conflicts recorded.
    wf = MeasurementWorkflow()
    assert wf._binding is None  # noqa: SLF001
    assert wf._paused is False  # noqa: SLF001
    assert wf._aborted is False  # noqa: SLF001
    assert wf._conflicting_replays == 0  # noqa: SLF001


def test_outcome_status_enum_has_expected_members() -> None:
    assert {s.value for s in MeasurementOutcomeStatus} == {
        "decided",
        "undetermined_deployment_late",
        "undetermined_aborted",
    }


# --------------------------------------------------------------------------- #
# Signal-handler bodies — called DIRECTLY on a bare instance (no live Temporal
# env; same technique as the __init__-state test above). @workflow.signal /
# @workflow.query only tag the methods with metadata — the underlying functions
# are ordinary methods and are safe to invoke off-server. This exercises the
# workflow.py shell's handler logic in the unit lane; the end-to-end behavior
# under a real Worker/timer is proven in tests/integration/measurement_workflow.
# --------------------------------------------------------------------------- #
REGISTRATION_HASH = "sha256:" + "a" * 64


def _bound_workflow() -> MeasurementWorkflow:
    """A bare instance with the run's expected registration hash set (normally
    ``run()`` sets it; the signal handlers read it, so we set it directly)."""
    wf = MeasurementWorkflow()
    wf._expected_registration_hash = REGISTRATION_HASH  # noqa: SLF001
    return wf


def test_first_deployment_confirmed_signal_binds_window() -> None:
    wf = _bound_workflow()
    accepted = make_accepted()
    wf.deployment_confirmed(accepted)  # first valid → START
    assert wf._binding is not None  # noqa: SLF001
    assert wf._binding.idempotency_key == accepted.confirmation.idempotency_key  # noqa: SLF001
    assert wf._pending_accepted is accepted  # noqa: SLF001
    assert wf._conflicting_replays == 0  # noqa: SLF001


def test_duplicate_deployment_confirmed_signal_is_noop_no_rebind() -> None:
    wf = _bound_workflow()
    accepted = make_accepted()
    wf.deployment_confirmed(accepted)
    first_binding = wf._binding  # noqa: SLF001
    # Byte-identical redelivery → DUPLICATE → no rebind, no conflict recorded.
    wf.deployment_confirmed(accepted)
    assert wf._binding is first_binding  # noqa: SLF001
    assert wf._conflicting_replays == 0  # noqa: SLF001


def test_conflicting_deployment_confirmed_signal_records_replay_keeps_original() -> None:
    wf = _bound_workflow()
    first = make_accepted(deployed_commit_sha="c1")
    wf.deployment_confirmed(first)
    first_binding = wf._binding  # noqa: SLF001
    # Same idempotency key, DIFFERENT content → CONFLICTING_REPLAY → recorded,
    # original binding retained (fail-closed, first wins).
    conflicting = make_accepted(deployed_commit_sha="c2")
    wf.deployment_confirmed(conflicting)
    assert wf._binding is first_binding  # noqa: SLF001
    assert wf._conflicting_replays == 1  # noqa: SLF001


def test_wrong_registration_deployment_confirmed_signal_never_binds() -> None:
    wf = _bound_workflow()
    wrong = make_accepted(registration_hash="sha256:" + "b" * 64)
    wf.deployment_confirmed(wrong)  # REFUSED_STRUCTURAL → no-op
    assert wf._binding is None  # noqa: SLF001
    assert wf._conflicting_replays == 0  # noqa: SLF001


def test_pause_and_resume_signals_toggle_pause_flag() -> None:
    wf = _bound_workflow()
    assert wf._paused is False  # noqa: SLF001
    wf.pause_observation()
    assert wf._paused is True  # noqa: SLF001
    wf.resume()
    assert wf._paused is False  # noqa: SLF001


def test_abort_signal_sets_aborted_flag() -> None:
    wf = _bound_workflow()
    assert wf._aborted is False  # noqa: SLF001
    wf.abort_measurement()
    assert wf._aborted is True  # noqa: SLF001


def test_status_query_projects_current_flags() -> None:
    wf = _bound_workflow()
    # Bind a window, pause, record a conflict — the query must reflect all of it.
    wf.deployment_confirmed(make_accepted(deployed_commit_sha="c1"))
    wf.deployment_confirmed(make_accepted(deployed_commit_sha="c2"))  # conflict
    wf.pause_observation()
    wf._window_days = 7  # noqa: SLF001 (normally set by run() after derive_window)
    status = wf.status()
    assert isinstance(status, MeasurementWorkflowStatus)
    assert status.window_bound is True
    assert status.paused is True
    assert status.aborted is False
    assert status.conflicting_replays == 1
    assert status.window_days == 7

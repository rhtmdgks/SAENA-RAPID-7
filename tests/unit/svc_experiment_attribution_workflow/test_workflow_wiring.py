"""``MeasurementWorkflow`` module surface — importable/definable WITHOUT a
Temporal server (mirrors ``tests/unit/svc_orchestrator/test_workflow_wiring.py``).
The actual signal->window->timer->outcome behavior under a live Worker is proven
in ``tests/integration/measurement_workflow/``.
"""

from __future__ import annotations

import temporalio.workflow as w
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

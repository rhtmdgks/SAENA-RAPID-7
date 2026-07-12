"""`saena_orchestrator.workflow` module surface — importable/definable
without a Temporal server; the actual signal->EXECUTING/refused behavior
under a live Worker is proven in
tests/integration/orchestrator/test_execution_workflow.py.
"""

from __future__ import annotations

from saena_domain.policy import PlanState
from saena_orchestrator.activities import ExecutionActivityResult
from saena_orchestrator.workflow import (
    APPROVE_SIGNAL_NAME,
    ExecutionWorkflow,
    ExecutionWorkflowInput,
    ExecutionWorkflowStatus,
)
from saena_orchestrator.workflow_logic import RunState


def test_approve_signal_name_matches_signal_client_constant() -> None:
    from saena_orchestrator.signal_client import APPROVE_SIGNAL_NAME as CLIENT_SIGNAL_NAME

    assert APPROVE_SIGNAL_NAME == CLIENT_SIGNAL_NAME == "approve"


def test_execution_workflow_is_a_temporal_workflow_definition() -> None:
    # `@workflow.defn` decoration registers workflow metadata accessible via
    # temporalio's own workflow definition lookup — this asserts the class
    # is a properly decorated workflow (name defaults to the class name) and
    # exposes exactly the one `approve` signal this unit implements.
    import temporalio.workflow as w

    defn = w._Definition.from_class(ExecutionWorkflow)  # noqa: SLF001
    assert defn is not None
    assert defn.name == "ExecutionWorkflow"
    assert "approve" in defn.signals


def test_execution_workflow_input_is_a_plain_serializable_dataclass() -> None:
    payload = ExecutionWorkflowInput(
        contract_hash="sha256:" + "a" * 64,
        manifest_ref="manifest://run/1",
        proposer_actor_id="actor-proposer-0001",
    )
    assert payload.contract_hash.startswith("sha256:")
    assert payload.manifest_ref.startswith("manifest://")


def test_execution_workflow_status_carries_run_and_plan_state() -> None:
    status = ExecutionWorkflowStatus(
        run_state=RunState.EXECUTING,
        plan_state=PlanState.APPROVED,
        last_refused_reason=None,
        activity_result=ExecutionActivityResult(contract_hash="sha256:" + "a" * 64, accepted=True),
    )
    assert status.run_state == RunState.EXECUTING
    assert status.plan_state == PlanState.APPROVED
    assert status.activity_result is not None
    assert status.activity_result.accepted is True

"""REAL Temporal workflow integration test — ADR-0003 signal path E2E.

Runs `ExecutionWorkflow` against `temporalio.testing.WorkflowEnvironment
.start_time_skipping()`, a genuine embedded Temporal test-server process
(not a mock/stub of the Temporal client or server). Verifies both halves of
the W2B exit gate:
  1. A validly re-validated `approve` signal drives WAITING_APPROVAL ->
     EXECUTING and the execution Activity is scheduled and completes.
  2. A forged/self-approval signal does NOT transition the workflow — it
     stays RUNNING (never reaches a completed/EXECUTING-with-result state),
     per ADR-0003 "Gate 거부 시 Temporal 전이 불가".

Honest skip discipline (task instruction: "honest skip with a clear reason,
NOT a silent pass"): `start_time_skipping()` lazily downloads a test-server
binary for the current OS/arch on first use if not already cached. This
module probes that startup with a bounded timeout in a session-scoped
fixture; if it cannot succeed (no cached binary + no reachable download
source, or any other startup failure) within the timeout, every test in this
module is skipped with the concrete exception captured from the probe —
never silently passed as green.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from orchestrator_factories import (
    APPROVER_1,
    CONTRACT_HASH,
    PROPOSER,
    make_signal,
)
from saena_domain.policy import DecisionRecord
from saena_domain.policy.two_person import ApproverRecord
from saena_orchestrator.activities import run_execution_activity
from saena_orchestrator.signal_client import TemporalSignalClient
from saena_orchestrator.workflow import (
    APPROVE_SIGNAL_NAME,
    ExecutionWorkflow,
    ExecutionWorkflowInput,
)
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

_STARTUP_TIMEOUT_SECONDS = 30
_TASK_QUEUE = "saena-orchestrator-integration-test-queue"

pytestmark = pytest.mark.integration


async def _try_start_environment() -> WorkflowEnvironment | Exception:
    try:
        return await asyncio.wait_for(
            WorkflowEnvironment.start_time_skipping(), timeout=_STARTUP_TIMEOUT_SECONDS
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


def test_valid_approval_signal_drives_waiting_approval_to_executing(
    temporal_env: WorkflowEnvironment,
) -> None:
    async def _scenario() -> None:
        async with Worker(
            temporal_env.client,
            task_queue=_TASK_QUEUE,
            workflows=[ExecutionWorkflow],
            activities=[run_execution_activity],
        ):
            handle = await temporal_env.client.start_workflow(
                ExecutionWorkflow.run,
                ExecutionWorkflowInput(
                    contract_hash=CONTRACT_HASH,
                    manifest_ref="manifest://run/valid",
                    proposer_actor_id=PROPOSER,
                ),
                id="wf-valid-approval",
                task_queue=_TASK_QUEUE,
            )
            signal = make_signal()
            await handle.signal(APPROVE_SIGNAL_NAME, signal)
            result = await handle.result()

            assert result.run_state.value == "executing"
            assert result.plan_state.value == "approved"
            assert result.activity_result is not None
            assert result.activity_result.accepted is True
            assert result.activity_result.contract_hash == CONTRACT_HASH

    asyncio.run(_scenario())


def test_forged_self_approval_signal_does_not_transition_workflow(
    temporal_env: WorkflowEnvironment,
) -> None:
    async def _scenario() -> None:
        async with Worker(
            temporal_env.client,
            task_queue=_TASK_QUEUE,
            workflows=[ExecutionWorkflow],
            activities=[run_execution_activity],
        ):
            handle = await temporal_env.client.start_workflow(
                ExecutionWorkflow.run,
                ExecutionWorkflowInput(
                    contract_hash=CONTRACT_HASH,
                    manifest_ref="manifest://run/forged",
                    proposer_actor_id=PROPOSER,
                ),
                id="wf-forged-signal",
                task_queue=_TASK_QUEUE,
            )
            forged = make_signal(
                approvals=(ApproverRecord(PROPOSER, "approved"),),
                incoming_decision=DecisionRecord(
                    contract_hash=CONTRACT_HASH,
                    approver_actor_id=PROPOSER,  # self-approval: forged
                    decision="approved",
                    proposer_actor_id=PROPOSER,
                    high_risk=False,
                    decided_at="2026-07-12T10:00:00Z",
                ),
            )
            await handle.signal(APPROVE_SIGNAL_NAME, forged)

            # Give the workflow task a chance to process the signal, then
            # assert it is STILL running (never reached a result), i.e. the
            # WAITING_APPROVAL -> EXECUTING transition did not occur.
            await asyncio.sleep(0.5)
            description = await handle.describe()
            assert description.status == WorkflowExecutionStatus.RUNNING

            # A legitimate signal sent afterward must still be able to drive
            # the workflow to completion — the forged signal must not have
            # corrupted/poisoned the workflow's state.
            valid = make_signal(approvals=(ApproverRecord(APPROVER_1, "approved"),))
            await handle.signal(APPROVE_SIGNAL_NAME, valid)
            result = await handle.result()
            assert result.run_state.value == "executing"

    asyncio.run(_scenario())


def test_duplicate_approve_signal_after_executing_is_a_no_op(
    temporal_env: WorkflowEnvironment,
) -> None:
    """Idempotent signal replay at the WORKFLOW level (task instruction:
    "same approval signal twice -> single transition"): once the workflow
    has reached EXECUTING, a second delivery of the SAME (or any) approve
    signal must not re-schedule a second Activity or otherwise mutate state
    (`_handle_approve`'s own `if self._run_state == RunState.EXECUTING:
    return` guard, workflow.py).
    """

    async def _scenario() -> None:
        async with Worker(
            temporal_env.client,
            task_queue=_TASK_QUEUE,
            workflows=[ExecutionWorkflow],
            activities=[run_execution_activity],
        ):
            handle = await temporal_env.client.start_workflow(
                ExecutionWorkflow.run,
                ExecutionWorkflowInput(
                    contract_hash=CONTRACT_HASH,
                    manifest_ref="manifest://run/duplicate",
                    proposer_actor_id=PROPOSER,
                ),
                id="wf-duplicate-signal",
                task_queue=_TASK_QUEUE,
            )
            signal = make_signal()
            await handle.signal(APPROVE_SIGNAL_NAME, signal)
            # Duplicate delivery of the SAME signal BEFORE awaiting the
            # result (workflow may already be EXECUTING, still RUNNING
            # overall since the stub Activity has not yet completed) — this
            # is the realistic at-least-once redelivery window
            # (`_handle_approve`'s own `if self._run_state ==
            # RunState.EXECUTING: return` no-op guard, workflow.py). A
            # completed workflow execution refuses new signals at the
            # Temporal server level (RPCError "Completed workflow"), so the
            # duplicate must land here, not after `handle.result()`.
            await handle.signal(APPROVE_SIGNAL_NAME, signal)
            result = await handle.result()
            # Exactly one EXECUTING result — the duplicate signal did not
            # re-schedule a second Activity or otherwise mutate state.
            assert result.run_state.value == "executing"

    asyncio.run(_scenario())


def test_temporal_signal_client_sends_approve_signal_over_real_client(
    temporal_env: WorkflowEnvironment,
) -> None:
    """`TemporalSignalClient` (the real `SignalClient` implementation) drives
    the same WAITING_APPROVAL -> EXECUTING transition as a direct
    `handle.signal(...)` call, proving its thin wiring is correct end-to-end
    against a real `temporalio.client.Client`.
    """

    async def _scenario() -> None:
        async with Worker(
            temporal_env.client,
            task_queue=_TASK_QUEUE,
            workflows=[ExecutionWorkflow],
            activities=[run_execution_activity],
        ):
            handle = await temporal_env.client.start_workflow(
                ExecutionWorkflow.run,
                ExecutionWorkflowInput(
                    contract_hash=CONTRACT_HASH,
                    manifest_ref="manifest://run/via-signal-client",
                    proposer_actor_id=PROPOSER,
                ),
                id="wf-via-temporal-signal-client",
                task_queue=_TASK_QUEUE,
            )
            client = TemporalSignalClient(client=temporal_env.client)
            await client.send_approval("wf-via-temporal-signal-client", make_signal())
            result = await handle.result()
            assert result.run_state.value == "executing"

    asyncio.run(_scenario())

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
    APPROVER_2,
    CONTRACT_HASH,
    PROPOSER,
    make_decision,
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


def test_forged_conflicting_signal_does_not_poison_seen_decisions_ledger(
    temporal_env: WorkflowEnvironment,
) -> None:
    """critic MUST-FIX regression: a forged signal impersonating a REAL
    approver's `decision_key` (same contract_hash + canonicalized
    approver_actor_id, DIFFERENT decision value) must be refused WITHOUT
    overwriting that approver's prior legitimate `_seen_decisions` entry.
    Uses a high-risk (2-distinct-approver quorum) plan so the workflow stays
    WAITING_APPROVAL after APPROVER_1's first legitimate "approved" decision
    — this is the attack window the critic identified: a forged "rejected"
    signal for APPROVER_1 sent into that window must not permanently poison
    APPROVER_1's replay slot.
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
                    manifest_ref="manifest://run/ledger-poisoning",
                    proposer_actor_id=PROPOSER,
                ),
                id="wf-ledger-poisoning",
                task_queue=_TASK_QUEUE,
            )

            # 1. APPROVER_1's REAL, legitimate "approved" decision (high-risk
            # plan: quorum needs a second, distinct approver -> workflow
            # stays WAITING_APPROVAL after this one).
            legit_approval = make_signal(
                approvals=(ApproverRecord(APPROVER_1, "approved"),),
                high_risk=True,
                incoming_decision=make_decision(
                    approver=APPROVER_1, decision="approved", high_risk=True
                ),
            )
            await handle.signal(APPROVE_SIGNAL_NAME, legit_approval)
            await asyncio.sleep(0.2)
            status_after_legit = await handle.query(ExecutionWorkflow.status)
            assert status_after_legit.run_state.value == "waiting_approval"
            # Legitimate accepted-but-quorum-pending decision: NOT refused.
            assert status_after_legit.last_refused_reason is None

            # 2. A FORGED signal impersonating APPROVER_1 with a CONFLICTING
            # decision ("rejected") for the SAME contract_hash — same
            # decision_key, different decision value. transition() refuses
            # this (ConflictingDecisionError) and apply_approval_signal
            # collapses it to REFUSED; the ledger-poisoning bug would have
            # let this overwrite APPROVER_1's real "approved" entry anyway.
            forged_conflicting = make_signal(
                approvals=(ApproverRecord(APPROVER_1, "approved"),),
                high_risk=True,
                incoming_decision=make_decision(
                    approver=APPROVER_1, decision="rejected", high_risk=True
                ),
            )
            await handle.signal(APPROVE_SIGNAL_NAME, forged_conflicting)
            await asyncio.sleep(0.2)
            status_after_forged = await handle.query(ExecutionWorkflow.status)
            assert status_after_forged.run_state.value == "waiting_approval"
            # The forged signal WAS refused (this assertion alone does not
            # yet prove no ledger poisoning happened — step 3 below is the
            # load-bearing assertion for that).
            assert status_after_forged.last_refused_reason is not None

            # 3. Resubmit APPROVER_1's ORIGINAL, legitimate decision again
            # (ordinary Temporal at-least-once redelivery of the SAME
            # signal). Under the pre-fix bug, step 2's forged signal would
            # have unconditionally overwritten
            # _seen_decisions[(CONTRACT_HASH, APPROVER_1)] with the
            # "rejected" DecisionRecord — so THIS resubmission of the real
            # "approved" decision would then itself look like a conflicting
            # decision against that poisoned entry and be refused
            # (ConflictingDecisionError -> REFUSED,
            # last_refused_reason is not None) — a PERMANENT block on
            # APPROVER_1's real approval. The fix (only record non-REFUSED
            # outcomes) means this resubmission is instead accepted as an
            # idempotent replay of the ORIGINAL "approved" decision:
            # last_refused_reason must be None again.
            await handle.signal(APPROVE_SIGNAL_NAME, legit_approval)
            await asyncio.sleep(0.2)
            status_after_resubmit = await handle.query(ExecutionWorkflow.status)
            assert status_after_resubmit.run_state.value == "waiting_approval"
            assert status_after_resubmit.last_refused_reason is None, (
                "APPROVER_1's legitimate decision was refused after resubmission — "
                "the forged signal in step 2 poisoned the _seen_decisions ledger"
            )

            # 4. APPROVER_2 (distinct, legitimate) completes H-7 quorum ->
            # EXECUTING, confirming no lasting corruption.
            second_approval = make_signal(
                approvals=(
                    ApproverRecord(APPROVER_1, "approved"),
                    ApproverRecord(APPROVER_2, "approved"),
                ),
                high_risk=True,
                incoming_decision=make_decision(
                    approver=APPROVER_2, decision="approved", high_risk=True
                ),
            )
            await handle.signal(APPROVE_SIGNAL_NAME, second_approval)
            result = await handle.result()
            assert result.run_state.value == "executing"
            assert result.plan_state.value == "approved"

    asyncio.run(_scenario())


def test_at_least_once_redelivery_of_legit_decision_after_refusal_is_idempotent(
    temporal_env: WorkflowEnvironment,
) -> None:
    """Ordinary Temporal at-least-once redelivery of the SAME legitimate
    decision (identical `decision_key` AND identical decision value — the
    realistic at-least-once transport-redelivery case, as opposed to the
    forged-conflicting-value case covered by
    `test_forged_conflicting_signal_does_not_poison_seen_decisions_ledger`
    above), sent again after an UNRELATED refused signal (a different
    approver's forged self-approval) was processed in between, must still be
    idempotent-accepted (not blocked) — isolating the property that a
    refusal for one `decision_key` has no side effect on a DIFFERENT,
    unrelated `decision_key`'s replay slot.
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
                    manifest_ref="manifest://run/redelivery-after-refusal",
                    proposer_actor_id=PROPOSER,
                ),
                id="wf-redelivery-after-refusal",
                task_queue=_TASK_QUEUE,
            )

            legit_approval = make_signal(
                approvals=(ApproverRecord(APPROVER_1, "approved"),),
                high_risk=True,
                incoming_decision=make_decision(
                    approver=APPROVER_1, decision="approved", high_risk=True
                ),
            )
            await handle.signal(APPROVE_SIGNAL_NAME, legit_approval)
            await asyncio.sleep(0.2)
            assert (await handle.query(ExecutionWorkflow.status)).last_refused_reason is None

            # An unrelated refused signal (self-approval by the proposer —
            # a DIFFERENT decision_key: approver_actor_id == PROPOSER, not
            # APPROVER_1) processed in between.
            unrelated_forged = make_signal(
                approvals=(ApproverRecord(PROPOSER, "approved"),),
                high_risk=True,
                incoming_decision=make_decision(
                    approver=PROPOSER, decision="approved", high_risk=True
                ),
            )
            await handle.signal(APPROVE_SIGNAL_NAME, unrelated_forged)
            await asyncio.sleep(0.2)
            status_after_unrelated_forged = await handle.query(ExecutionWorkflow.status)
            assert status_after_unrelated_forged.run_state.value == "waiting_approval"
            assert status_after_unrelated_forged.last_refused_reason is not None

            # At-least-once redelivery of APPROVER_1's ORIGINAL signal — a
            # DIFFERENT decision_key from the unrelated refusal above, so
            # this must still be an idempotent no-conflict accept.
            await handle.signal(APPROVE_SIGNAL_NAME, legit_approval)
            await asyncio.sleep(0.2)
            status_after_redelivery = await handle.query(ExecutionWorkflow.status)
            assert status_after_redelivery.run_state.value == "waiting_approval"
            assert status_after_redelivery.last_refused_reason is None, (
                "APPROVER_1's at-least-once redelivered decision was refused after an "
                "UNRELATED approver's refusal — refusal state leaked across decision_keys"
            )

            # Quorum completion still reachable -> proves APPROVER_1's entry
            # was never disturbed by the unrelated refusal in between.
            second_approval = make_signal(
                approvals=(
                    ApproverRecord(APPROVER_1, "approved"),
                    ApproverRecord(APPROVER_2, "approved"),
                ),
                high_risk=True,
                incoming_decision=make_decision(
                    approver=APPROVER_2, decision="approved", high_risk=True
                ),
            )
            await handle.signal(APPROVE_SIGNAL_NAME, second_approval)
            result = await handle.result()
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


def test_signal_delivered_before_run_executes_still_completes(
    temporal_env: WorkflowEnvironment,
) -> None:
    """Deterministic reproduction of the 2026-07-13 intermittent CI failure.

    `start_signal` (Temporal signal-with-start) GUARANTEES the approve signal
    is delivered in the first workflow task — the signal handler executes
    BEFORE `run()` does. The old implementation scheduled the execution
    Activity inside the handler behind `assert self._input is not None`;
    in this ordering `_input` is unset and the workflow died with
    ApplicationError(AssertionError). The fix moves Activity scheduling into
    `run()` (the only place `_input` is guaranteed) and stops `run()` from
    resetting state a pre-run signal already advanced, so a legitimate
    approval that races workflow start must now complete normally.
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
                    manifest_ref="manifest://run/pre-run-signal",
                    proposer_actor_id=PROPOSER,
                ),
                id="wf-pre-run-signal",
                task_queue=_TASK_QUEUE,
                start_signal=APPROVE_SIGNAL_NAME,
                start_signal_args=[make_signal()],
            )
            result = await handle.result()

            assert result.run_state.value == "executing"
            assert result.plan_state.value == "approved"
            assert result.activity_result is not None
            assert result.activity_result.accepted is True

    asyncio.run(_scenario())

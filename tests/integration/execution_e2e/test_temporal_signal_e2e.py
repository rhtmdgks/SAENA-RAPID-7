"""Step 6 — Temporal execution signal, against a REAL `temporalio.testing.
WorkflowEnvironment.start_time_skipping()` server (same honest-skip
discipline as `tests/integration/orchestrator/test_execution_workflow.py`:
a bounded-timeout probe that skips this WHOLE module with the concrete
startup exception if the test-server binary cannot be obtained, never a
silent pass).

Wires the REAL approval decision this suite's steps 3-5 produce (via the
SAME `plan-contract-service` + `policy-gate-service` HTTP path `tests/e2e/
execution/test_synthetic_tenant_execution_e2e.py` exercises) into a REAL
`ExecutionWorkflow` instance through `TemporalSignalClient` — the ADR-0003
signal path this repo's own `agent-orchestrator-service/README.md`
documents as NOT YET connected end-to-end: "plan-contract-service does NOT
yet call `TemporalSignalClient` ... Wiring the caller ... is a follow-up
integration, not part of either patch unit's exclusive-write scope." This
test IS that follow-up integration, built as test-harness glue (never a
change to either service's own exclusive-write path) — it constructs the
`ApprovalSignal` from the REAL `DecisionRecord`/`contract_hash`/
`PlanSnapshot` facts plan-contract-service's decision endpoint actually
produced, then sends it via `TemporalSignalClient.send_approval(...)`
exactly as a real caller eventually would.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from approval_factories import decision_body, load_change_plan_fixture
from execution_e2e_harness import PlanApprovalHarness
from saena_domain.identity.http import TENANT_HEADER_NAME
from saena_domain.policy import DecisionRecord, PlanSnapshot
from saena_domain.policy.two_person import ApproverRecord
from saena_orchestrator.activities import run_execution_activity
from saena_orchestrator.signal_client import TemporalSignalClient
from saena_orchestrator.workflow import (
    APPROVE_SIGNAL_NAME,
    ExecutionWorkflow,
    ExecutionWorkflowInput,
)
from saena_orchestrator.workflow_logic import ApprovalSignal
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

pytestmark = pytest.mark.integration

_STARTUP_TIMEOUT_SECONDS = 30
_TASK_QUEUE = "execution-e2e-temporal-signal-queue"

TENANT_1 = "e2e-tenant-one"
RUN_ID = "run-e2e-0001"
PATCH_UNIT_ID = "PU-01"
PROPOSER = "actor-proposer-e2e"
APPROVER_1 = "actor-approver-e2e-1"


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
def temporal_env(_probe_result: WorkflowEnvironment | Exception) -> WorkflowEnvironment:
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


@pytest.fixture
def approved_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[PlanApprovalHarness, str]:
    """Steps 3-5, real HTTP round trip: propose + Policy-Gate-validate +
    approve a ChangePlan against the REAL plan-contract-service /
    policy-gate-service apps — this fixture is this module's own bridge
    into the SAME approval authority path
    `test_synthetic_tenant_execution_e2e.py` exercises, so this module's
    Temporal signal carries a genuinely-approved `contract_hash`, not a
    fabricated one."""
    # policy-gate-service reconciles `X-Saena-Tenant-Id` against the
    # process `SAENA_TENANT_ID` env var at request time (ADR-0014).
    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_1)
    harness = PlanApprovalHarness(tenant_id=TENANT_1)
    change_plan = load_change_plan_fixture("single-patch-unit.json", tenant_id=TENANT_1)
    change_plan["run_id"] = RUN_ID
    proposer_headers = {TENANT_HEADER_NAME: TENANT_1, "X-Saena-Actor-Id": PROPOSER}

    propose_response = harness.plan_contract_client.post(
        "/v1/plans", json=change_plan, headers=proposer_headers
    )
    assert propose_response.status_code == 201, propose_response.text
    contract_hash = propose_response.json()["contract_hash"]

    harness.gate_adapter.configure_request_facts(
        tenant_id=TENANT_1,
        contract_hash=contract_hash,
        proposer_actor_id=PROPOSER,
        approver_actor_id=APPROVER_1,
        approved_scope=tuple(change_plan["approved_scope"]),
    )
    decision_response = harness.plan_contract_client.post(
        f"/v1/plans/{contract_hash}/decisions",
        json=decision_body(
            contract_hash,
            approver_actor_id=APPROVER_1,
            run_id=RUN_ID,
            patch_unit_id=PATCH_UNIT_ID,
            tenant_id=TENANT_1,
        ),
        headers=proposer_headers,
    )
    assert decision_response.status_code == 200, decision_response.text
    assert decision_response.json()["state"] == "approved"

    yield harness, contract_hash
    harness.close()


def _approval_signal_from_real_decision(contract_hash: str) -> ApprovalSignal:
    """Build the `ApprovalSignal` this workflow's `approve` handler
    re-validates, from the SAME `contract_hash`/decision facts the real
    plan-contract-service decision endpoint above just produced (ADR-0003
    step 4 defense-in-depth re-check, over genuinely-approved data)."""
    snapshot = PlanSnapshot(contract_hash=contract_hash, content_fingerprint="fp-e2e-1")
    decision = DecisionRecord(
        contract_hash=contract_hash,
        approver_actor_id=APPROVER_1,
        decision="approved",
        proposer_actor_id=PROPOSER,
        high_risk=False,
        decided_at="2026-07-13T00:00:00Z",
    )
    return ApprovalSignal(
        contract_hash=contract_hash,
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(APPROVER_1, "approved"),),
        high_risk=False,
        decided_at="2026-07-13T00:00:00Z",
        incoming_decision=decision,
        plan_snapshot=snapshot,
        stored_plan_snapshot=snapshot,
        gate_decision_ref="gate-decision-e2e-0001",
    )


def test_real_approved_decision_drives_temporal_signal_to_executing(
    temporal_env: WorkflowEnvironment,
    approved_plan: tuple[PlanApprovalHarness, str],
) -> None:
    _harness, contract_hash = approved_plan
    signal = _approval_signal_from_real_decision(contract_hash)

    async def scenario() -> None:
        async with Worker(
            temporal_env.client,
            task_queue=_TASK_QUEUE,
            workflows=[ExecutionWorkflow],
            activities=[run_execution_activity],
        ):
            handle = await temporal_env.client.start_workflow(
                ExecutionWorkflow.run,
                ExecutionWorkflowInput(
                    contract_hash=contract_hash,
                    manifest_ref=f"manifest://{TENANT_1}/{RUN_ID}/{PATCH_UNIT_ID}",
                    proposer_actor_id=PROPOSER,
                ),
                id=f"wf-e2e-{contract_hash[-8:]}",
                task_queue=_TASK_QUEUE,
            )

            # Send the signal via the REAL `TemporalSignalClient` (the
            # production caller-side port), never a bare `handle.signal(...)`
            # — proves the actual wiring a real plan-contract-service ->
            # Temporal integration would use.
            client = TemporalSignalClient(client=temporal_env.client)
            await client.send_approval(handle.id, signal)

            result = await handle.result()
            assert result.run_state.value == "executing"
            assert result.plan_state.value == "approved"
            assert result.activity_result is not None
            assert result.activity_result.accepted is True
            assert result.activity_result.contract_hash == contract_hash

    asyncio.run(scenario())


def test_forged_signal_for_a_real_contract_hash_does_not_transition(
    temporal_env: WorkflowEnvironment,
    approved_plan: tuple[PlanApprovalHarness, str],
) -> None:
    """Same REAL, genuinely-approved `contract_hash` as the happy path
    above, but the signal itself is forged (self-approval by the proposer)
    — the workflow must stay WAITING_APPROVAL/RUNNING, never EXECUTING,
    even though `contract_hash` is entirely legitimate (ADR-0003 "Gate 거부
    시 Temporal 전이 불가" — proven here against a real approved plan, not
    just a synthetic fixture)."""
    _harness, contract_hash = approved_plan
    snapshot = PlanSnapshot(contract_hash=contract_hash, content_fingerprint="fp-e2e-1")
    forged_decision = DecisionRecord(
        contract_hash=contract_hash,
        approver_actor_id=PROPOSER,  # self-approval: forged
        decision="approved",
        proposer_actor_id=PROPOSER,
        high_risk=False,
        decided_at="2026-07-13T00:00:00Z",
    )
    forged_signal = ApprovalSignal(
        contract_hash=contract_hash,
        proposer_actor_id=PROPOSER,
        approvals=(ApproverRecord(PROPOSER, "approved"),),
        high_risk=False,
        decided_at="2026-07-13T00:00:00Z",
        incoming_decision=forged_decision,
        plan_snapshot=snapshot,
        stored_plan_snapshot=snapshot,
        gate_decision_ref="gate-decision-e2e-0001",
    )

    async def scenario() -> None:
        async with Worker(
            temporal_env.client,
            task_queue=_TASK_QUEUE,
            workflows=[ExecutionWorkflow],
            activities=[run_execution_activity],
        ):
            handle = await temporal_env.client.start_workflow(
                ExecutionWorkflow.run,
                ExecutionWorkflowInput(
                    contract_hash=contract_hash,
                    manifest_ref=f"manifest://{TENANT_1}/{RUN_ID}/{PATCH_UNIT_ID}",
                    proposer_actor_id=PROPOSER,
                ),
                id=f"wf-e2e-forged-{contract_hash[-8:]}",
                task_queue=_TASK_QUEUE,
            )
            await handle.signal(APPROVE_SIGNAL_NAME, forged_signal)
            await asyncio.sleep(0.5)
            description = await handle.describe()
            assert description.status == WorkflowExecutionStatus.RUNNING

    asyncio.run(scenario())

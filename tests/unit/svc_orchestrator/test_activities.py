"""Stub execution Activity — pure-logic assertions.

`temporalio.activity.heartbeat()` requires a live Activity execution context
(it raises `RuntimeError("Not in activity context")` outside a Worker) — this
unit test therefore monkeypatches `activity.heartbeat` to a no-op so
`run_execution_activity`'s own result-shape logic can be exercised without a
Worker. The REAL heartbeat call, under a live Worker/Activity context, is
proven in tests/integration/orchestrator/test_execution_workflow.py.
"""

from __future__ import annotations

import asyncio

import pytest
from saena_orchestrator.activities import (
    ExecutionActivityInput,
    ExecutionActivityResult,
    run_execution_activity,
)
from temporalio import activity


def test_run_execution_activity_returns_accepted_result_for_valid_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(activity, "heartbeat", lambda *args, **kwargs: None)
    activity_input = ExecutionActivityInput(
        contract_hash="sha256:" + "a" * 64, manifest_ref="manifest://run/1"
    )
    result = asyncio.run(run_execution_activity(activity_input))
    assert result == ExecutionActivityResult(contract_hash="sha256:" + "a" * 64, accepted=True)


def test_run_execution_activity_calls_heartbeat_with_contract_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(activity, "heartbeat", lambda *args: calls.append(args))
    activity_input = ExecutionActivityInput(
        contract_hash="sha256:" + "c" * 64, manifest_ref="manifest://run/2"
    )
    asyncio.run(run_execution_activity(activity_input))
    assert calls
    assert activity_input.contract_hash in calls[0]

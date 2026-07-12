"""SignalClient local port — the surface plan-contract-service calls to send
the Temporal `approve` signal (ADR-0003 step 3: "Policy Gate 승인 시에만
plan-contract-service가 Temporal signal을 직접 발송").

plan-contract-service HOLDS the authority to invoke this (it is the caller);
this service EXPOSES the receiving side. Per this unit's task spec ("no
cross-service imports... a local signal-client Protocol") and the
import-linter `services-are-independent` contract (`.importlinter`), this
module must not import `saena_plan_contract`, and `saena_plan_contract` must
not import this module — the only legal coupling is this Protocol shape (a
service-boundary contract analogous to plan-contract-service's own
`PolicyGateClient` port pattern) plus, at deploy time, an out-of-process
Temporal client/gRPC call that plan-contract-service makes directly against
the Temporal server (not against this package).

This module therefore models BOTH sides of that boundary, entirely within
saena_orchestrator's own exclusive-write path:
  - `SignalClient` (Protocol): the shape a caller (plan-contract-service, in
    its own process/package) would implement or wrap around a real
    `temporalio.client.Client.get_workflow_handle(...).signal(...)` call to
    reach this workflow's `approve` signal.
  - `TemporalSignalClient`: a real implementation over a
    `temporalio.client.Client`, for use by whichever process actually holds
    the authority to send the signal (out of this patch unit's scope to wire
    into plan-contract-service — see README "OPEN").
  - `FakeSignalClient`: an in-process test double recording every signal sent,
    for unit tests that only need to assert "a signal was sent with payload
    X", without a live Temporal server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from saena_orchestrator.workflow_logic import ApprovalSignal

if TYPE_CHECKING:
    import temporalio.client

APPROVE_SIGNAL_NAME = "approve"


@runtime_checkable
class SignalClient(Protocol):
    """Local port — the caller-side surface for sending the `approve` signal
    to a running `ExecutionWorkflow` instance identified by `workflow_id`.
    """

    async def send_approval(self, workflow_id: str, signal: ApprovalSignal) -> None:
        """Send `signal` to the `approve` signal handler of the
        `ExecutionWorkflow` identified by `workflow_id`.

        Implementations MUST NOT interpret or re-validate `signal` — all
        re-validation happens inside the workflow (defense-in-depth,
        ADR-0003 step 4); this port is a transport-only surface.
        """
        ...


@dataclass
class TemporalSignalClient:
    """Real `SignalClient` over a live `temporalio.client.Client`.

    Deliberately thin: it only resolves a workflow handle and calls
    `.signal(APPROVE_SIGNAL_NAME, signal)` — all decision-making happens
    inside the workflow's own signal handler (`workflow.py`), never here.
    Which process constructs and holds this client (plan-contract-service, at
    deploy time, via its own `temporalio.client.Client` — not a Python import
    of this package) is OUT OF SCOPE for this patch unit; see README "OPEN".
    """

    client: temporalio.client.Client

    async def send_approval(self, workflow_id: str, signal: ApprovalSignal) -> None:
        handle = self.client.get_workflow_handle(workflow_id)
        await handle.signal(APPROVE_SIGNAL_NAME, signal)


@dataclass
class FakeSignalClient:
    """In-process test double — records every signal sent, no live Temporal
    server required. Used by tests exercising the caller-side contract of
    this port without depending on `TemporalSignalClient`/a real client.
    """

    sent: list[tuple[str, ApprovalSignal]] = field(default_factory=list)

    async def send_approval(self, workflow_id: str, signal: ApprovalSignal) -> None:
        self.sent.append((workflow_id, signal))


__all__ = ["APPROVE_SIGNAL_NAME", "FakeSignalClient", "SignalClient", "TemporalSignalClient"]

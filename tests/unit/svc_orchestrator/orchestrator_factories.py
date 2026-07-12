"""Factory helpers shared by `tests/unit/svc_orchestrator` and
`tests/integration/orchestrator`."""

from __future__ import annotations

from saena_domain.policy import DecisionRecord, PlanSnapshot
from saena_domain.policy.two_person import ApproverRecord
from saena_orchestrator.workflow_logic import ApprovalSignal

CONTRACT_HASH = "sha256:" + "a" * 64
OTHER_CONTRACT_HASH = "sha256:" + "b" * 64
PROPOSER = "actor-proposer-0001"
APPROVER_1 = "actor-approver-0001"
APPROVER_2 = "actor-approver-0002"
DECIDED_AT = "2026-07-12T10:00:00Z"
GATE_DECISION_REF = "gate-decision-0001"


def make_snapshot(
    *, contract_hash: str = CONTRACT_HASH, content_fingerprint: str = "fp-1"
) -> PlanSnapshot:
    return PlanSnapshot(contract_hash=contract_hash, content_fingerprint=content_fingerprint)


def make_decision(
    approver: str = APPROVER_1,
    decision: str = "approved",
    *,
    high_risk: bool = False,
    contract_hash: str = CONTRACT_HASH,
    proposer_actor_id: str = PROPOSER,
) -> DecisionRecord:
    return DecisionRecord(
        contract_hash=contract_hash,
        approver_actor_id=approver,
        decision=decision,
        proposer_actor_id=proposer_actor_id,
        high_risk=high_risk,
        decided_at=DECIDED_AT,
    )


def make_signal(
    *,
    contract_hash: str = CONTRACT_HASH,
    proposer_actor_id: str = PROPOSER,
    approvals: tuple[ApproverRecord, ...] = (ApproverRecord(APPROVER_1, "approved"),),
    high_risk: bool = False,
    incoming_decision: DecisionRecord | None = None,
    plan_snapshot: PlanSnapshot | None = None,
    stored_plan_snapshot: PlanSnapshot | None = None,
    gate_decision_ref: str = GATE_DECISION_REF,
) -> ApprovalSignal:
    snapshot = (
        plan_snapshot if plan_snapshot is not None else make_snapshot(contract_hash=contract_hash)
    )
    stored = (
        stored_plan_snapshot
        if stored_plan_snapshot is not None
        else make_snapshot(contract_hash=contract_hash)
    )
    decision = (
        incoming_decision
        if incoming_decision is not None
        else make_decision(contract_hash=contract_hash, proposer_actor_id=proposer_actor_id)
    )
    return ApprovalSignal(
        contract_hash=contract_hash,
        proposer_actor_id=proposer_actor_id,
        approvals=approvals,
        high_risk=high_risk,
        decided_at=DECIDED_AT,
        incoming_decision=decision,
        plan_snapshot=snapshot,
        stored_plan_snapshot=stored,
        gate_decision_ref=gate_decision_ref,
    )


__all__ = [
    "APPROVER_1",
    "APPROVER_2",
    "CONTRACT_HASH",
    "DECIDED_AT",
    "GATE_DECISION_REF",
    "OTHER_CONTRACT_HASH",
    "PROPOSER",
    "make_decision",
    "make_signal",
    "make_snapshot",
]

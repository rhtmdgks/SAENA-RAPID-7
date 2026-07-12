"""Thin request/response DTOs for the plan-contract-service HTTP API.

Request bodies re-validate against the GENERATED `ChangeplanActionContract`
(`saena_schemas.domain.change_plan_v1`) / `ApprovalDecision`
(`saena_schemas.domain.approval_decision_v1`) models — no duplicate field
lists here, per ADR-0011 "no duplicate DTOs". These wrapper models exist only
for the thin envelope FastAPI needs around the generated contract models
(e.g. `GET` responses need `state` + `decisions` alongside the stored plan,
none of which the generated `ChangeplanActionContract` model itself carries).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from saena_schemas.domain.approval_decision_v1 import ApprovalDecision
from saena_schemas.domain.change_plan_v1 import ChangeplanActionContract


class ProposePlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_hash: str
    state: str


class DecisionRecordView(BaseModel):
    """Actor-id-only projection of a recorded decision (no PII beyond
    `approver_actor_id`, task spec instruction "GET ... actor_id only, no
    PII")."""

    model_config = ConfigDict(extra="forbid")

    approver_actor_id: str
    decision: str
    decided_at: str


class PlanStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_hash: str
    state: str
    decisions: list[DecisionRecordView]


class DecisionSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_hash: str
    state: str
    approver_actor_id: str
    decision: str


class TransitionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_hash: str
    state: str


class ExecutionCheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_hash: str
    execution_allowed: bool


__all__ = [
    "ApprovalDecision",
    "ChangeplanActionContract",
    "DecisionRecordView",
    "DecisionSubmitResponse",
    "ExecutionCheckResponse",
    "PlanStateResponse",
    "ProposePlanResponse",
    "TransitionResponse",
]

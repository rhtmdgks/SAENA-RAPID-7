"""Request/response body models for the policy-gate HTTP surface.

Hand-written pydantic v2 models (NOT codegen output — this service's HTTP
request/response shapes are not yet backed by a `packages/contracts` JSON
Schema; only `ChangePlan`/`ApprovalDecision` themselves are codegen SSOT,
consumed via `saena_policy_gate.service.PlanCheckInput`, not re-declared
here).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RequestKindLiteral = Literal["command", "file", "network", "tool"]


class AuthorizeRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RequestKindLiteral
    action: str = Field(min_length=1)
    resource: list[str] = Field(default_factory=list)
    pipeline: list[list[str]] | None = None
    approver_actor_id: str = Field(min_length=1)


class GateDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["allow", "deny"]
    reasons: list[str]
    require_two_person: bool
    decision_key: list[str]
    error_code: str | None = None


class DiffStatsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files_changed: int = Field(ge=0)
    lines_changed: int = Field(ge=0)


class PlanCheckRequestBody(BaseModel):
    """Minimal ChangePlan projection this route needs — task instruction 2
    ("input ChangePlan (generated model)"). Callers submit the same field
    values the generated `ChangeplanActionContract` model carries; this
    body deliberately accepts a narrowed subset (the H-3/H-7-relevant
    fields) rather than requiring every ChangePlan field a full Action
    Contract needs, keeping this route usable ahead of end-to-end
    ChangePlan submission wiring (out of scope for this patch unit).
    """

    model_config = ConfigDict(extra="forbid")

    contract_hash: str = Field(min_length=1)
    proposer_actor_id: str = Field(min_length=1)
    approver_actor_id: str = Field(min_length=1)
    evidence_ledger_hash: str = Field(min_length=1)
    approved_scope: list[str] = Field(min_length=1)
    scope_max_globs: int = Field(ge=1)
    diff_max_files: int = Field(ge=1)
    diff_max_lines: int = Field(ge=1)
    hypothesis_risks: list[Literal["low", "medium", "high"]] = Field(default_factory=list)
    diff_stats: DiffStatsBody | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


__all__ = [
    "AuthorizeRequestBody",
    "DiffStatsBody",
    "GateDecisionResponse",
    "HealthResponse",
    "PlanCheckRequestBody",
    "RequestKindLiteral",
]

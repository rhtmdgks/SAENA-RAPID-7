"""RFC 9457 problem-detail error hierarchy for `saena_plan_contract` (ADR-0015).

Spec basis: `docs/decisions/ADR-0015-canonical-error-model.md` — `error_code`
taxonomy `saena.<category>.<reason>`, 9 categories, `policy_denied` category
explicitly includes `saena.policy_denied.gate_unavailable` as the fail-closed
gate-outage case (ADR-0003 "policy-gate = fail-closed"). Every error here
carries the `status`/`retryable` pair `problem_response()` needs to build a
`common/problem-detail/v1` document — the actual HTTP response construction
(FastAPI `JSONResponse`, `type`/`instance` URIs, `trace_id` fill-in) happens
in `app.py`, which is the only place a framework dependency belongs.
"""

from __future__ import annotations

from typing import Any


class PlanContractError(Exception):
    """Base class for every error raised by `saena_plan_contract`.

    Attributes mirror `saena_domain.persistence.errors.PersistenceError` /
    `saena_domain.identity.errors.IdentityError` (same `error_code` + log-safe
    `context` shape) so the services-layer problem-detail mapper in `app.py`
    can treat every raised error uniformly.
    """

    error_code: str = "saena.internal.unexpected"
    status: int = 500
    retryable: bool = False
    title: str = "Internal error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), **self.context}


class ValidationFailedError(PlanContractError):
    """Request body failed ChangePlan/ApprovalDecision schema validation."""

    error_code = "saena.validation.schema_mismatch"
    status = 400
    retryable = False
    title = "Request failed schema validation"


class PlanNotFoundError(PlanContractError):
    """No ChangePlan is stored for the requested `contract_hash`."""

    error_code = "saena.not_found.resource_missing"
    status = 404
    retryable = False
    title = "Plan not found"


class ContractHashMismatchError(PlanContractError):
    """`ApprovalDecision.contract_hash` does not match the path `contract_hash`."""

    error_code = "saena.validation.contract_hash_mismatch"
    status = 400
    retryable = False
    title = "Decision contract_hash does not match plan"


class PlanContractHashViolationError(PlanContractError):
    """Re-propose reused a `contract_hash` with mutated content (H-3/H-7
    post-approval immutability — `saena_domain.policy.ContractHashViolationError`
    surfaced as a 409, per contract-catalog.md "승인 후 immutable")."""

    error_code = "saena.conflict.contract_hash_violation"
    status = 409
    retryable = False
    title = "contract_hash reused with different content"


class ConflictingDecisionSubmittedError(PlanContractError):
    """Same approver submitted two non-identical decisions for one plan
    (`saena_domain.policy.ConflictingDecisionError` surfaced as a 409)."""

    error_code = "saena.conflict.decision_conflict"
    status = 409
    retryable = False
    title = "Conflicting decision already recorded"


class InvalidPlanStateTransitionError(PlanContractError):
    """Requested action is not legal from the plan's current `PlanState`
    (`saena_domain.policy.InvalidTransitionError` surfaced as a 409)."""

    error_code = "saena.conflict.invalid_transition"
    status = 409
    retryable = False
    title = "Action not permitted from the plan's current state"


class SelfApprovalRejectedError(PlanContractError):
    """The approver is the plan's own proposer (H-7 self-approval ban)."""

    error_code = "saena.policy_denied.self_approval"
    status = 403
    retryable = False
    title = "Self-approval is forbidden"


class PolicyGateDeniedError(PlanContractError):
    """ADR-0003 step (1): the policy gate denied this plan/decision."""

    error_code = "saena.policy_denied.gate_denied"
    status = 403
    retryable = False
    title = "Policy gate denied this request"


class PolicyGateUnavailableError(PlanContractError):
    """ADR-0003 / security-model.md "policy-gate = fail-closed": the gate is
    unreachable, timed out, or returned a non-200 response. Approval is
    IMPOSSIBLE while this holds — never treated as an implicit allow."""

    error_code = "saena.policy_denied.gate_unavailable"
    status = 503
    retryable = True
    title = "Policy gate unavailable — failing closed"


class ExecutionNotApprovedError(PlanContractError):
    """`saena_domain.policy.guard_execution` blocked execution — the plan is
    not (yet) `APPROVED` with a valid approval decision. This is the
    "승인 전 실행 차단" invariant surface for w2-15 (agent-orchestrator)."""

    error_code = "saena.policy_denied.execution_not_approved"
    status = 403
    retryable = False
    title = "Execution blocked: plan is not approved"

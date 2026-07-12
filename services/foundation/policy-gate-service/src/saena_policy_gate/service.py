"""Service-layer orchestration: fail-closed evaluation, H-3 plan-check, and
idempotent decision recording.

Fail-closed contract (ADR-0015 `policy_denied.gate_unavailable`,
security-model.md "policy-gate = fail-closed"): every public entry point in
this module (`authorize_command`, `check_plan`) wraps its engine/domain
evaluation in a `try/except Exception` that converts ANY unexpected failure
— a broken rule store, an evaluation-time exception, a timeout the caller
already turned into an exception — into a `deny` `GateResult` carrying
`error_code="saena.policy_denied.gate_unavailable"`. There is no code path
in this module that lets an engine exception propagate as an ambiguous 500;
the fail-closed doctrine is enforced at this one choke point rather than
scattered per-route.

`policy.decision.recorded.v1` (README "Published events") is a PROPOSED
AsyncAPI topic — `docs/architecture/api-event-contracts.md` "신규 토픽 후보"
lists it, and it is absent from the CONFIRMED v1 catalog
(`packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml`, 12 channels,
none named `policy.decision.recorded.v1`). `saena_domain.events.
EnvelopeFactory` validates `event_type` against that catalog's declared
channels, so building/recording an envelope for an unconfirmed topic through
that factory would raise, not silently succeed. Per this unit's task
instruction ("do NOT publish to outbox; persist decision record + structured
log; document why"), this module therefore records every decision via
`DecisionRecordPort` (persisted, queryable, idempotent) plus a structured
log line (tenant-safe, `saena_observability`) — no `OutboxPort.record` call
anywhere in this module. When `policy.decision.recorded.v1` is promoted to
CONFIRMED in a future contracts patch unit, outbox publication can be added
here without changing this module's decision-recording contract.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from saena_domain.identity import TenantId
from saena_domain.persistence.errors import DecisionConflictError as _PortDecisionConflictError
from saena_domain.persistence.ports import DecisionRecordPort
from saena_domain.policy import DecisionRecord, evaluate_h3_evidence_policy, is_high_risk_plan
from saena_domain.policy.evidence import DiffStats, H3PolicyResult

from saena_policy_gate.engine import AuthorizationRequest, Decision, PolicyEngine
from saena_policy_gate.errors import DecisionConflictError, GateUnavailableError

logger = logging.getLogger("saena_policy_gate")


def _now_iso() -> str:
    """RFC3339 UTC, `Z`-suffixed, matching `TimestampUtc`'s schema pattern
    (`^[0-9]{4}-...T...(\\.[0-9]+)?Z$`) — single `datetime.now(UTC)` call so
    the date/time and millisecond components can never straddle a clock
    tick (two separate `now()` calls would risk that race)."""
    now = datetime.now(UTC)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class GateResult:
    """Signed-decision-shaped outcome returned by every route in this
    service (`{decision, reasons[], require_two_person, decision_key}`,
    per this unit's task instruction 2)."""

    decision: str  # "allow" | "deny"
    reasons: tuple[str, ...]
    require_two_person: bool
    decision_key: tuple[str, str]
    error_code: str | None = None


def _record(
    *,
    store: DecisionRecordPort,
    tenant_id: TenantId,
    contract_hash: str,
    approver_actor_id: str,
    decision: str,
    proposer_actor_id: str,
    high_risk: bool,
) -> DecisionRecord:
    """Idempotently persist a `DecisionRecord` via `store` (replay-safe:
    identical `decision_key` + identical `decision` value is a no-op;
    conflicting `decision` for the same key raises
    `saena_policy_gate.errors.DecisionConflictError`, mapped to HTTP 409 by
    the RFC 9457 layer).
    """
    record = DecisionRecord(
        contract_hash=contract_hash,
        approver_actor_id=approver_actor_id,
        decision=decision,
        proposer_actor_id=proposer_actor_id,
        high_risk=high_risk,
        decided_at=_now_iso(),
    )
    try:
        stored = store.record(tenant_id, record)
    except _PortDecisionConflictError as exc:
        raise DecisionConflictError(str(exc), context=exc.context) from exc
    logger.info(
        "policy decision recorded",
        extra={
            "saena_attributes": {
                "decision_key": list(stored.decision_key),
                "decision": stored.decision,
                "high_risk": stored.high_risk,
            }
        },
    )
    return stored


def authorize_command(
    *,
    engine: PolicyEngine,
    store: DecisionRecordPort,
    tenant_id: TenantId,
    request: AuthorizationRequest,
    approver_actor_id: str,
) -> GateResult:
    """POST /v1/gate/authorize — command/file/network/tool authorization
    (task instruction 3). Every decision is recorded, allow or deny.
    """
    contract_hash = f"authz:{request.kind}:{request.action}:{','.join(request.resource)}"
    try:
        verdict: Decision = engine.evaluate(request)
    except Exception as exc:  # noqa: BLE001 — fail-closed choke point (see module docstring)
        logger.warning(
            "policy engine evaluation failed — failing closed",
            extra={"saena_attributes": {"error": str(exc)}},
        )
        stored = _record(
            store=store,
            tenant_id=tenant_id,
            contract_hash=contract_hash,
            approver_actor_id=approver_actor_id,
            decision="rejected",
            proposer_actor_id="system",
            high_risk=False,
        )
        return GateResult(
            decision="deny",
            reasons=("policy engine unavailable — failing closed",),
            require_two_person=False,
            decision_key=stored.decision_key,
            error_code=GateUnavailableError.error_code,
        )

    decision_value = "approved" if verdict.allow else "rejected"
    stored = _record(
        store=store,
        tenant_id=tenant_id,
        contract_hash=contract_hash,
        approver_actor_id=approver_actor_id,
        decision=decision_value,
        proposer_actor_id="system",
        high_risk=False,
    )
    return GateResult(
        decision="allow" if verdict.allow else "deny",
        reasons=verdict.reasons,
        require_two_person=False,
        decision_key=stored.decision_key,
    )


@dataclass(frozen=True, slots=True)
class PlanCheckInput:
    """Minimal plan-check input this module needs — a subset of the
    generated `ChangeplanActionContract` model's fields (task instruction 2:
    "runs H-3 evidence policy ... scope-glob check, risk classification").
    Built by the route handler from the request body; kept as a plain
    dataclass here so `saena_domain.policy.evaluate_h3_evidence_policy`'s
    `_ChangePlanLike` Protocol is satisfied without this module importing
    the generated pydantic model directly (decoupled from codegen output
    shape drift).
    """

    contract_hash: str
    proposer_actor_id: str
    evidence_ledger_hash: str
    approved_scope: list[str]
    scope_max_globs: int
    diff_max_files: int
    diff_max_lines: int
    hypothesis_risks: tuple[str, ...]
    diff_stats: DiffStats | None = None


class _ScopeLimitsView:
    max_globs: int

    def __init__(self, max_globs: int) -> None:
        self.max_globs = max_globs


class _DiffBudgetView:
    max_files: int
    max_lines: int

    def __init__(self, max_files: int, max_lines: int) -> None:
        self.max_files = max_files
        self.max_lines = max_lines


class _ChangePlanView:
    """Adapter satisfying `saena_domain.policy.evidence._ChangePlanLike` at
    RUNTIME (structural duck-typing, exercised by every `check_plan` test in
    this unit's suite).

    `_ChangePlanLike` and its own nested `_ScopeLimits`/`_DiffBudget`
    Protocols are underscore-prefixed (module-private, not in
    `saena_domain.policy.evidence.__all__` and not re-exported by
    `saena_domain.policy`) — this module cannot import and reuse those exact
    Protocol types by name. mypy additionally treats mutable Protocol
    attributes invariantly, so even a locally-redeclared same-shaped class
    (`_ScopeLimitsView`/`_DiffBudgetView` below) does not statically unify
    with the private Protocol's own identity one level down (`diff_budget`/
    `scope_limits` themselves). `evaluate_h3_evidence_policy`'s call site
    below therefore takes this class through `typing.cast` to the Protocol's
    public-facing parameter type — a `cast`, not an `Any`-suppression, so
    every OTHER call site in this module keeps full type checking; only the
    one unavoidable private-Protocol-identity boundary is bridged.
    """

    def __init__(self, plan: PlanCheckInput) -> None:
        self.evidence_ledger_hash = plan.evidence_ledger_hash
        self.approved_scope = plan.approved_scope
        self.scope_limits = _ScopeLimitsView(plan.scope_max_globs)
        self.diff_budget = _DiffBudgetView(plan.diff_max_files, plan.diff_max_lines)


def check_plan(
    *,
    store: DecisionRecordPort,
    tenant_id: TenantId,
    plan: PlanCheckInput,
    approver_actor_id: str,
) -> GateResult:
    """POST /v1/gate/plan-check — H-3 evidence policy + risk classification
    (task instruction 2). Fail-closed on any evaluation exception, same
    choke-point shape as `authorize_command`.
    """
    high_risk = is_high_risk_plan(plan.hypothesis_risks)
    try:
        # cast: see _ChangePlanView's docstring — bridges a private,
        # unimportable Protocol identity one level down (diff_budget/
        # scope_limits), not a general type-safety escape hatch.
        result: H3PolicyResult = evaluate_h3_evidence_policy(
            cast(Any, _ChangePlanView(plan)), diff_stats=plan.diff_stats
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed choke point (see module docstring)
        logger.warning(
            "H-3 evidence policy evaluation failed — failing closed",
            extra={"saena_attributes": {"error": str(exc)}},
        )
        stored = _record(
            store=store,
            tenant_id=tenant_id,
            contract_hash=plan.contract_hash,
            approver_actor_id=approver_actor_id,
            decision="rejected",
            proposer_actor_id=plan.proposer_actor_id,
            high_risk=high_risk,
        )
        return GateResult(
            decision="deny",
            reasons=("policy engine unavailable — failing closed",),
            require_two_person=high_risk,
            decision_key=stored.decision_key,
            error_code=GateUnavailableError.error_code,
        )

    decision_value = "approved" if result.ok else "rejected"
    stored = _record(
        store=store,
        tenant_id=tenant_id,
        contract_hash=plan.contract_hash,
        approver_actor_id=approver_actor_id,
        decision=decision_value,
        proposer_actor_id=plan.proposer_actor_id,
        high_risk=high_risk,
    )
    return GateResult(
        decision="allow" if result.ok else "deny",
        reasons=result.violations if not result.ok else ("H-3 evidence policy satisfied",),
        require_two_person=high_risk,
        decision_key=stored.decision_key,
    )


__all__ = [
    "GateResult",
    "PlanCheckInput",
    "authorize_command",
    "check_plan",
]

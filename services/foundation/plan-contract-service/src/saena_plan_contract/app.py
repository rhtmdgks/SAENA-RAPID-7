"""FastAPI app factory for plan-contract-service — ADR-0003 approval path.

Endpoints (task spec):
    POST   /v1/plans                                — propose a ChangePlan
    POST   /v1/plans/{contract_hash}/decisions       — submit an ApprovalDecision
    POST   /v1/plans/{contract_hash}/cancel          — cancel (proposer/operator)
    POST   /v1/plans/{contract_hash}/expire          — expire the approval window
    GET    /v1/plans/{contract_hash}                 — state + decisions
    POST   /v1/plans/{contract_hash}/execution-check — guard_execution choke point

ADR-0003 authority order, enforced IN CODE inside `submit_decision` (not
merely documented): (1) `gate.plan_check` — deny => 403 `policy_denied`
+ audit record, gate down => 503 `gate_unavailable` FAIL CLOSED, in BOTH
cases returning/raising BEFORE `saena_domain.policy.transition` is ever
called; (2) `transition()` with stored/presented `PlanSnapshot`s (H-3/H-7
immutability choke) + `DecisionRecord` idempotent replay/conflict semantics +
H-7 two-person via `high_risk`/gate `require_two_person`; (3) on APPROVED:
issue per-patch-unit lease records, outbox-record `plan.contract.approved.v1`
(payload WITHOUT `approver_actor_id`, ADR-0024(e)-2), audit-trail record.
Rejected/cancelled/expired paths also produce audit descriptors.

`_PlanFacts` (module-private, per-app instance): `PlanRepository`
(`saena_domain.persistence`, w2-07) stores only `PlanSnapshot`
(contract_hash + content_fingerprint) and `PlanState` — it does not retain
the full `ChangePlan` body (out of that port's scope). This service needs a
few plan-level facts back at decision/execution-check time (proposer
actor_id for the self-approval check, the high-risk derivation, patch_unit
ids for lease issuance, run_id for the approved-event envelope) that only
exist in the body `propose_plan` parsed. `_PlanFacts` is this service's own
tenant-scoped, in-process bookkeeping for that — not a domain port, not
routed through the audit trail, and not itself PII (proposer_actor_id is
already carried by the audit trail's `SUBMITTED_FOR_APPROVAL` record; the
side table exists so this module does not have to string-match audit reason
codes to recover typed facts).
"""

# ruff: noqa: B008 — `Depends(...)` in an argument default is the standard,
# required FastAPI dependency-injection idiom (every route handler in this
# module uses it); B008's generic "no function call in defaults" mutable-
# default-argument warning does not apply to FastAPI's own `Depends` marker,
# which FastAPI evaluates per-request rather than once at function-definition
# time. Scoped to this file only (the file whose entire content is FastAPI
# route signatures) — not a repo-wide config change, kept local to this
# unit's exclusive-write path.

from __future__ import annotations

import datetime as _dt
import threading
from typing import Any, Protocol, cast

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from saena_domain.events import EnvelopeFactory
from saena_domain.identity import (
    TENANT_HEADER_NAME,
    TenantId,
    TenantMismatchError,
    reconcile_tenant,
)
from saena_domain.persistence import NotFoundError as RepoNotFoundError
from saena_domain.persistence import OutboxPort, PlanRepository
from saena_domain.persistence.errors import DecisionConflictError
from saena_domain.policy import (
    AuditReasonCode,
    AuditTrailRecord,
    ConflictingDecisionError,
    ContractHashViolationError,
    DecisionRecord,
    ExecutionBlockedError,
    InvalidTransitionError,
    PlanSnapshot,
    PlanState,
    canonical_actor_id,
    evaluate_h3_evidence_policy,
    guard_execution,
    is_high_risk_plan,
    issue_lease,
)
from saena_domain.policy.transitions import cancel as policy_cancel
from saena_domain.policy.transitions import expire as policy_expire
from saena_domain.policy.transitions import transition as policy_transition
from saena_domain.policy.two_person import ApproverRecord

from saena_plan_contract.audit_trail import AuditTrailStore
from saena_plan_contract.contract_hash import compute_contract_hash
from saena_plan_contract.errors import (
    ConflictingDecisionSubmittedError,
    ContractHashMismatchError,
    ExecutionNotApprovedError,
    InvalidPlanStateTransitionError,
    PlanContractError,
    PlanContractHashViolationError,
    PlanNotFoundError,
    PolicyGateDeniedError,
    SelfApprovalRejectedError,
    ValidationFailedError,
)
from saena_plan_contract.gate_client import GateCheckRequest, PolicyGateClient
from saena_plan_contract.schemas import (
    ApprovalDecision,
    ChangeplanActionContract,
    DecisionRecordView,
    DecisionSubmitResponse,
    ExecutionCheckResponse,
    PlanStateResponse,
    ProposePlanResponse,
    TransitionResponse,
)


class _ScopeLimitsLike(Protocol):
    max_globs: int


class _DiffBudgetLike(Protocol):
    max_files: int
    max_lines: int


class _ChangePlanLike(Protocol):
    """Local mirror of `saena_domain.policy.evidence._ChangePlanLike` (a
    PRIVATE, underscore-prefixed Protocol not importable from this service)
    — see the `cast` call site in `propose_plan` for why this exists."""

    evidence_ledger_hash: object
    approved_scope: list[str]
    scope_limits: _ScopeLimitsLike
    diff_budget: _DiffBudgetLike


_PRODUCER = "plan-contract-service"
_EVENT_PROPOSED = "plan.contract.proposed.v1"
_EVENT_APPROVED = "plan.contract.approved.v1"

# Reason code used for the audit descriptor recorded on a policy-gate deny —
# saena_domain.policy.AuditReasonCode has no dedicated "gate denied" member
# (that vocabulary is scoped to saena_domain.policy's OWN transition/quorum
# reasons); this service maps a gate deny onto the closed enum's closest
# existing member (QUORUM_PENDING: the plan remains WAITING_APPROVAL, no
# state change occurred) rather than inventing a parallel free-text reason,
# preserving "reason is a closed code, not free text" (audit.py docstring).
# OPEN ITEM: a future saena_domain.policy revision could add a dedicated
# GATE_DENIED reason code; flagged in the final report rather than editing
# packages/domain (outside this unit's exclusive-write paths).
_POLICY_GATE_DENIED_REASON = AuditReasonCode.QUORUM_PENDING


def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonicalize(change_plan_dict: dict[str, Any]) -> str:
    """`contract_hash`-shaped content fingerprint — see `contract_hash.py`
    module docstring for the interim-canonicalization OPEN ITEM."""
    return compute_contract_hash(change_plan_dict)


class _PlanFacts:
    """Per-app, tenant-scoped bookkeeping — see module docstring."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._facts: dict[tuple[str, str], dict[str, Any]] = {}

    def put(
        self,
        tenant_id: TenantId,
        contract_hash: str,
        *,
        proposer_actor_id: str,
        high_risk: bool,
        patch_unit_ids: tuple[str, ...],
        run_id: str,
    ) -> None:
        with self._lock:
            self._facts[(tenant_id.value, contract_hash)] = {
                "proposer_actor_id": proposer_actor_id,
                "high_risk": high_risk,
                "patch_unit_ids": patch_unit_ids,
                "run_id": run_id,
            }

    def get(self, tenant_id: TenantId, contract_hash: str) -> dict[str, Any]:
        with self._lock:
            facts = self._facts.get((tenant_id.value, contract_hash))
        if facts is None:
            raise PlanNotFoundError(
                f"no plan facts stored for contract_hash {contract_hash!r}",
                context={"contract_hash": contract_hash},
            )
        return facts


def _require_tenant(request: Request) -> TenantId:
    """ADR-0014 synchronous HTTP path: `X-Saena-Tenant-Id` header vs.
    `SAENA_TENANT_ID` pod env. Tenant-safe: relies on
    `TenantMismatchError.context` (already structured/log-safe) for any
    logging a caller of this dependency chooses to do — this function itself
    never logs the raw header value."""
    header_value = request.headers.get(TENANT_HEADER_NAME)
    env_value = request.app.state.tenant_env_value
    reconciled = reconcile_tenant(header_value, env_value)
    return TenantId(reconciled)


def _plan_repo(request: Request) -> PlanRepository:
    return request.app.state.plans


def _outbox(request: Request) -> OutboxPort:
    return request.app.state.outbox


def _gate(request: Request) -> PolicyGateClient:
    return request.app.state.gate


def _audit_trail(request: Request) -> AuditTrailStore:
    return request.app.state.audit_trail


def _facts(request: Request) -> _PlanFacts:
    return request.app.state.plan_facts


def _problem_response(exc: PlanContractError, request: Request) -> JSONResponse:
    """RFC 9457 `application/problem+json` mapping (ADR-0015)."""
    trace_id = request.headers.get("X-Saena-Trace-Id") or "0" * 32
    category = exc.error_code.split(".", 2)[1] if "." in exc.error_code else "internal"
    body: dict[str, Any] = {
        "type": f"https://schemas.the-saena.ai/errors/{category}/{exc.error_code}",
        "title": exc.title,
        "status": exc.status,
        "detail": str(exc),
        "error_code": exc.error_code,
        "retryable": exc.retryable,
        "trace_id": trace_id,
    }
    return JSONResponse(status_code=exc.status, content=body, media_type="application/problem+json")


def _audit(trail: AuditTrailStore, tenant_id: TenantId, record: AuditTrailRecord) -> None:
    trail.append(tenant_id, record)


def _load_decisions(
    plans: PlanRepository, tenant_id: TenantId, contract_hash: str
) -> tuple[dict[tuple[str, str], DecisionRecord], tuple[ApproverRecord, ...]]:
    stored = plans.get_decisions(tenant_id, contract_hash)
    seen = {d.decision_key: d for d in stored}
    approvals = tuple(ApproverRecord(d.approver_actor_id, d.decision) for d in stored)
    return seen, approvals


def create_app(
    *,
    plans: PlanRepository,
    outbox: OutboxPort,
    gate: PolicyGateClient,
    audit_trail: AuditTrailStore | None = None,
    tenant_env_value: str | None = None,
) -> FastAPI:
    """Build the plan-contract-service FastAPI app.

    `tenant_env_value` mirrors `SAENA_TENANT_ID` (ADR-0014) — a single pod is
    scoped to one tenant; every request's `X-Saena-Tenant-Id` header must
    reconcile against it. Injectable for tests (the real process entrypoint
    reads the actual pod env var — out of this factory's scope).
    """
    app = FastAPI(title="saena-plan-contract")
    app.state.plans = plans
    app.state.outbox = outbox
    app.state.gate = gate
    app.state.audit_trail = audit_trail or AuditTrailStore()
    app.state.plan_facts = _PlanFacts()
    app.state.tenant_env_value = tenant_env_value

    @app.exception_handler(PlanContractError)
    async def _handle_plan_contract_error(request: Request, exc: PlanContractError) -> JSONResponse:
        return _problem_response(exc, request)

    @app.exception_handler(TenantMismatchError)
    async def _handle_tenant_mismatch(request: Request, exc: TenantMismatchError) -> JSONResponse:
        mapped = PlanContractError(str(exc), context=exc.context)
        mapped.error_code = "saena.auth.tenant_mismatch"
        mapped.status = 403
        mapped.retryable = False
        mapped.title = "Tenant header/env mismatch"
        return _problem_response(mapped, request)

    # --- POST /v1/plans -----------------------------------------------------

    @app.post("/v1/plans", response_model=ProposePlanResponse, status_code=201)
    def propose_plan(
        body: dict[str, Any],
        request: Request,
        tenant_id: TenantId = Depends(_require_tenant),
        plans: PlanRepository = Depends(_plan_repo),
        outbox: OutboxPort = Depends(_outbox),
        trail: AuditTrailStore = Depends(_audit_trail),
        facts: _PlanFacts = Depends(_facts),
    ) -> ProposePlanResponse:
        try:
            plan = ChangeplanActionContract.model_validate(body)
        except ValidationError as exc:
            raise ValidationFailedError(
                "ChangePlan failed schema validation", context={"detail": str(exc)}
            ) from exc

        if plan.tenant_id.root != tenant_id.value:
            raise ValidationFailedError(
                "ChangePlan.tenant_id does not match the request's reconciled tenant",
                context={
                    "plan_tenant_id": plan.tenant_id.root,
                    "request_tenant_id": tenant_id.value,
                },
            )

        # evaluate_h3_evidence_policy's parameter type is a PRIVATE,
        # structural Protocol (saena_domain.policy.evidence._ChangePlanLike,
        # leading underscore — not part of that module's public API, so it
        # cannot be imported here to type-annotate an adapter against it).
        # The generated `ChangeplanActionContract` model satisfies it at
        # RUNTIME (duck-typed: evaluate_h3_evidence_policy only ever calls
        # `str(evidence_ledger_hash)` and reads `.max_globs`/`.max_files`/
        # `.max_lines`, all present) but mypy's structural match on the
        # generated Pydantic `RootModel`/nested-model field TYPES (e.g.
        # `Sha256Ref` vs the Protocol's bare `object`) is stricter than the
        # runtime contract requires — `cast` documents that gap explicitly
        # rather than silencing it with a blanket `type: ignore`.
        h3_result = evaluate_h3_evidence_policy(cast(_ChangePlanLike, plan))
        if not h3_result.ok:
            raise ValidationFailedError(
                "ChangePlan failed H-3 evidence/scope/diff-budget policy",
                context={"violations": list(h3_result.violations)},
            )

        proposer_actor_id = request.headers.get("X-Saena-Actor-Id", "")
        if not proposer_actor_id:
            raise ValidationFailedError(
                "X-Saena-Actor-Id header is required to identify the proposer"
            )

        plan_dict = plan.model_dump(mode="json")
        contract_hash = _canonicalize(plan_dict)
        fingerprint = contract_hash

        # PROPOSED -> WAITING_APPROVAL submission (task spec: "store snapshot
        # ... set_state WAITING_APPROVAL via PROPOSED->submit"). No stored
        # plan exists for a brand-new contract_hash, so transition()'s
        # immutability choke point is intentionally not exercised here (see
        # that function's own docstring: PROPOSED->WAITING_APPROVAL has "no
        # stored plan to compare against yet"). A re-propose under the SAME
        # contract_hash with DIFFERENT content is caught explicitly below
        # (409) before any transition/store write happens.
        try:
            existing = plans.get_plan(tenant_id, contract_hash)
        except RepoNotFoundError:
            existing = None
        if existing is not None and existing.content_fingerprint != fingerprint:
            raise PlanContractHashViolationError(
                f"contract_hash {contract_hash!r} already stored with different content",
                context={"contract_hash": contract_hash},
            )

        high_risk = is_high_risk_plan(tuple(h.risk.value for h in plan.hypotheses))

        snapshot = PlanSnapshot(contract_hash=contract_hash, content_fingerprint=fingerprint)
        plans.put_plan(tenant_id, snapshot)

        outcome = policy_transition(
            PlanState.PROPOSED,
            contract_hash=contract_hash,
            proposer_actor_id=proposer_actor_id,
            approvals=(),
            high_risk=high_risk,
            decided_at=_now_iso(),
        )
        plans.set_state(tenant_id, contract_hash, outcome.state)
        _audit(trail, tenant_id, outcome.audit_record)
        facts.put(
            tenant_id,
            contract_hash,
            proposer_actor_id=proposer_actor_id,
            high_risk=high_risk,
            patch_unit_ids=tuple(pu.id for pu in plan.patch_units),
            run_id=plan.run_id.root,
        )

        envelope = EnvelopeFactory.build_tenant_envelope(
            producer=_PRODUCER,
            event_type=_EVENT_PROPOSED,
            tenant_id=tenant_id.value,
            run_id=plan.run_id.root,
            idempotency_key=contract_hash,
            payload={
                "contract_uri": f"saena-plan-contract://plans/{contract_hash}",
                "contract_hash": contract_hash,
                "base_commit": plan.repo_commit.root,
                "evidence_ids": sorted({eid for h in plan.hypotheses for eid in h.evidence_ids}),
                "patch_unit_ids": [pu.id for pu in plan.patch_units],
                "evidence_ledger_hash": plan.evidence_ledger_hash.root,
            },
        )
        outbox.record(envelope)

        return ProposePlanResponse(contract_hash=contract_hash, state=outcome.state.value)

    # --- GET /v1/plans/{contract_hash} --------------------------------------

    @app.get("/v1/plans/{contract_hash}", response_model=PlanStateResponse)
    def get_plan_state(
        contract_hash: str,
        tenant_id: TenantId = Depends(_require_tenant),
        plans: PlanRepository = Depends(_plan_repo),
    ) -> PlanStateResponse:
        try:
            state = plans.get_state(tenant_id, contract_hash)
        except RepoNotFoundError as exc:
            raise PlanNotFoundError(
                f"no plan stored for contract_hash {contract_hash!r}",
                context={"contract_hash": contract_hash},
            ) from exc
        decisions = plans.get_decisions(tenant_id, contract_hash)
        return PlanStateResponse(
            contract_hash=contract_hash,
            state=state.value,
            decisions=[
                DecisionRecordView(
                    approver_actor_id=d.approver_actor_id,
                    decision=d.decision,
                    decided_at=d.decided_at,
                )
                for d in decisions
            ],
        )

    # --- POST /v1/plans/{contract_hash}/decisions ---------------------------

    @app.post(
        "/v1/plans/{contract_hash}/decisions",
        response_model=DecisionSubmitResponse,
    )
    def submit_decision(
        contract_hash: str,
        body: dict[str, Any],
        tenant_id: TenantId = Depends(_require_tenant),
        plans: PlanRepository = Depends(_plan_repo),
        outbox: OutboxPort = Depends(_outbox),
        gate: PolicyGateClient = Depends(_gate),
        trail: AuditTrailStore = Depends(_audit_trail),
        facts: _PlanFacts = Depends(_facts),
    ) -> DecisionSubmitResponse:
        try:
            decision_body = ApprovalDecision.model_validate(body)
        except ValidationError as exc:
            raise ValidationFailedError(
                "ApprovalDecision failed schema validation", context={"detail": str(exc)}
            ) from exc

        if decision_body.contract_hash.root != contract_hash:
            raise ContractHashMismatchError(
                "ApprovalDecision.contract_hash does not match the path contract_hash",
                context={
                    "path_contract_hash": contract_hash,
                    "body_contract_hash": decision_body.contract_hash.root,
                },
            )

        try:
            snapshot = plans.get_plan(tenant_id, contract_hash)
        except RepoNotFoundError as exc:
            raise PlanNotFoundError(
                f"no plan stored for contract_hash {contract_hash!r}",
                context={"contract_hash": contract_hash},
            ) from exc
        current_state = plans.get_state(tenant_id, contract_hash)
        plan_facts = facts.get(tenant_id, contract_hash)
        proposer_actor_id: str = plan_facts["proposer_actor_id"]
        high_risk: bool = plan_facts["high_risk"]

        # --- Idempotent replay short-circuit (task spec instruction 4) ---------
        # `saena_domain.policy.transition()`'s own WAITING_APPROVAL-scoped
        # replay detection (seen_decisions) cannot fire once the plan has
        # already reached a TERMINAL state (APPROVED/REJECTED) — every
        # _ALLOWED_TRANSITIONS edge out of a terminal state is empty by
        # design, so transition() correctly raises InvalidTransitionError for
        # ANY further call, replay or not. This service-layer check runs
        # BEFORE the gate call and BEFORE transition() precisely to
        # distinguish "identical decision resubmitted after the plan already
        # settled" (200, no-op, no gate re-check, no new outbox event) from a
        # genuine attempt to change a settled plan's outcome (still a 409 via
        # the InvalidTransitionError branch below). Both derive `decision_key`
        # the same way saena_domain.policy.DecisionRecord does (contract_hash
        # + canonical_actor_id(approver_actor_id)), so a case/whitespace
        # variant of the same approver replaying the same decision value
        # still counts as the identical replay it is.
        if current_state in (PlanState.APPROVED, PlanState.REJECTED):
            prior_decisions = plans.get_decisions(tenant_id, contract_hash)
            replay_key = (
                contract_hash,
                canonical_actor_id(decision_body.approver_actor_id.root),
            )
            prior = next((d for d in prior_decisions if d.decision_key == replay_key), None)
            if prior is not None and prior.decision == decision_body.decision.value:
                return DecisionSubmitResponse(
                    contract_hash=contract_hash,
                    state=current_state.value,
                    approver_actor_id=prior.approver_actor_id,
                    decision=prior.decision,
                )

        # --- ADR-0003 step (1): Policy Gate pre-check, BEFORE transition() -----
        # Deny => 403 policy_denied + audit record, no transition attempted.
        # Gate down => 503 gate_unavailable FAIL CLOSED, no transition
        # attempted — this branch is the ADR-0003/W2A exit-demo path.
        gate_request = GateCheckRequest(
            contract_hash=contract_hash,
            tenant_id=tenant_id.value,
            high_risk=high_risk,
        )
        # gate.plan_check raises PolicyGateUnavailableError on any transport
        # failure/timeout/non-200 (fail-closed) — propagates unmodified, the
        # PlanContractError exception handler above maps it to 503.
        gate_decision = gate.plan_check(gate_request)
        if not gate_decision.allow:
            _audit(
                trail,
                tenant_id,
                AuditTrailRecord(
                    contract_hash=contract_hash,
                    actor_id=decision_body.approver_actor_id.root,
                    decided_at=_now_iso(),
                    from_state=current_state,
                    to_state=current_state,
                    reason_code=_POLICY_GATE_DENIED_REASON,
                ),
            )
            raise PolicyGateDeniedError(
                "policy gate denied this decision",
                context={"reasons": list(gate_decision.reasons), "contract_hash": contract_hash},
            )

        # --- ADR-0003 step (2): saena_domain.policy.transition() ---------------
        seen, prior_approvals = _load_decisions(plans, tenant_id, contract_hash)
        incoming = DecisionRecord(
            contract_hash=contract_hash,
            approver_actor_id=decision_body.approver_actor_id.root,
            decision=decision_body.decision.value,
            proposer_actor_id=proposer_actor_id,
            high_risk=high_risk or gate_decision.require_two_person,
            decided_at=decision_body.decided_at.root,
        )
        canonical_incoming = canonical_actor_id(incoming.approver_actor_id)
        already_present = any(
            canonical_actor_id(a.approver_actor_id) == canonical_incoming for a in prior_approvals
        )
        approvals = (
            prior_approvals
            if already_present
            else (*prior_approvals, ApproverRecord(incoming.approver_actor_id, incoming.decision))
        )

        try:
            outcome = policy_transition(
                current_state,
                contract_hash=contract_hash,
                proposer_actor_id=proposer_actor_id,
                approvals=approvals,
                high_risk=incoming.high_risk,
                decided_at=_now_iso(),
                seen_decisions=seen,
                incoming_decision=incoming,
                stored_plan=snapshot,
                presented_plan=snapshot,
            )
        except InvalidTransitionError as exc:
            if canonical_incoming == canonical_actor_id(proposer_actor_id):
                raise SelfApprovalRejectedError(
                    "approver_actor_id equals the plan's own proposer_actor_id",
                    context={"contract_hash": contract_hash},
                ) from exc
            raise InvalidPlanStateTransitionError(
                str(exc), context={"contract_hash": contract_hash}
            ) from exc
        except ConflictingDecisionError as exc:
            raise ConflictingDecisionSubmittedError(
                str(exc), context={"contract_hash": contract_hash}
            ) from exc
        except ContractHashViolationError as exc:  # pragma: no cover
            # Defense-in-depth (ADR-0003 "Temporal 재검증 = defense-in-depth"
            # applied at this layer too): guard_immutability() cannot
            # actually fire from THIS call site today, because `stored_plan`
            # and `presented_plan` above are both the SAME `snapshot` object
            # read from `plans.get_plan` moments earlier in this handler — by
            # construction they always compare equal to themselves. This
            # branch exists so that if a future revision of this endpoint
            # accepts a caller-presented plan body/fingerprint alongside the
            # ApprovalDecision (rather than only a contract_hash reference)
            # and passes it as `presented_plan`, the H-3/H-7 post-approval
            # immutability choke point is already wired to a 409, not a
            # silent pass-through — never remove this handler while
            # `guard_immutability` remains part of `transition()`'s contract.
            raise PlanContractHashViolationError(
                str(exc), context={"contract_hash": contract_hash}
            ) from exc

        # Persist the decision (idempotent by decision_key at the repo layer
        # too — DecisionConflictError mirrors ConflictingDecisionError; kept
        # as a defensive second check even though the domain-layer
        # transition() call above already validated the same conflict using
        # its OWN `seen`/`approvals` view sourced from this same repo read).
        try:
            plans.record_decision(tenant_id, incoming)
        except DecisionConflictError as exc:
            raise ConflictingDecisionSubmittedError(
                str(exc), context={"contract_hash": contract_hash}
            ) from exc
        plans.set_state(tenant_id, contract_hash, outcome.state)
        _audit(trail, tenant_id, outcome.audit_record)

        # Idempotency (task spec instruction 4): only emit the
        # plan.contract.approved.v1 envelope / issue leases on an ACTUAL
        # state CHANGE — a replay of an already-applied identical decision
        # short-circuits BEFORE any of that. A rebuilt envelope would carry a
        # NEW event_id even for byte-identical payload content, which the
        # outbox's event_id-keyed idempotency cannot dedup against the first
        # recording — so this branch, not the outbox, is what prevents the
        # duplicate.
        state_changed = outcome.state != current_state
        if state_changed and outcome.state == PlanState.APPROVED:
            for patch_unit_id in plan_facts["patch_unit_ids"]:
                issue_lease(
                    patch_unit_id=patch_unit_id,
                    scope=(),
                    expiry=incoming.decided_at,
                )
            approved_envelope = EnvelopeFactory.build_tenant_envelope(
                producer=_PRODUCER,
                event_type=_EVENT_APPROVED,
                tenant_id=tenant_id.value,
                run_id=plan_facts["run_id"],
                idempotency_key=f"{contract_hash}:approved",
                # ADR-0024(e)-2: approver_actor_id deliberately excluded.
                payload={"contract_hash": contract_hash, "decision": "approved"},
            )
            outbox.record(approved_envelope)
        elif state_changed and outcome.state == PlanState.REJECTED:
            rejected_envelope = EnvelopeFactory.build_tenant_envelope(
                producer=_PRODUCER,
                event_type=_EVENT_APPROVED,
                tenant_id=tenant_id.value,
                run_id=plan_facts["run_id"],
                idempotency_key=f"{contract_hash}:rejected",
                payload={"contract_hash": contract_hash, "decision": "rejected"},
            )
            outbox.record(rejected_envelope)

        return DecisionSubmitResponse(
            contract_hash=contract_hash,
            state=outcome.state.value,
            approver_actor_id=incoming.approver_actor_id,
            decision=incoming.decision,
        )

    # --- POST /v1/plans/{contract_hash}/cancel ------------------------------

    @app.post("/v1/plans/{contract_hash}/cancel", response_model=TransitionResponse)
    def cancel_plan(
        contract_hash: str,
        request: Request,
        tenant_id: TenantId = Depends(_require_tenant),
        plans: PlanRepository = Depends(_plan_repo),
        trail: AuditTrailStore = Depends(_audit_trail),
    ) -> TransitionResponse:
        try:
            current_state = plans.get_state(tenant_id, contract_hash)
        except RepoNotFoundError as exc:
            raise PlanNotFoundError(
                f"no plan stored for contract_hash {contract_hash!r}",
                context={"contract_hash": contract_hash},
            ) from exc
        actor_id = request.headers.get("X-Saena-Actor-Id", "")
        by_operator = request.headers.get("X-Saena-Operator", "false").lower() == "true"
        try:
            outcome = policy_cancel(
                current_state,
                contract_hash=contract_hash,
                actor_id=actor_id,
                decided_at=_now_iso(),
                by_operator=by_operator,
            )
        except InvalidTransitionError as exc:
            raise InvalidPlanStateTransitionError(
                str(exc), context={"contract_hash": contract_hash}
            ) from exc
        plans.set_state(tenant_id, contract_hash, outcome.state)
        _audit(trail, tenant_id, outcome.audit_record)
        return TransitionResponse(contract_hash=contract_hash, state=outcome.state.value)

    # --- POST /v1/plans/{contract_hash}/expire ------------------------------

    @app.post("/v1/plans/{contract_hash}/expire", response_model=TransitionResponse)
    def expire_plan(
        contract_hash: str,
        request: Request,
        tenant_id: TenantId = Depends(_require_tenant),
        plans: PlanRepository = Depends(_plan_repo),
        trail: AuditTrailStore = Depends(_audit_trail),
    ) -> TransitionResponse:
        try:
            current_state = plans.get_state(tenant_id, contract_hash)
        except RepoNotFoundError as exc:
            raise PlanNotFoundError(
                f"no plan stored for contract_hash {contract_hash!r}",
                context={"contract_hash": contract_hash},
            ) from exc
        actor_id = request.headers.get("X-Saena-Actor-Id", "")
        try:
            outcome = policy_expire(
                current_state,
                contract_hash=contract_hash,
                actor_id=actor_id,
                decided_at=_now_iso(),
            )
        except InvalidTransitionError as exc:
            raise InvalidPlanStateTransitionError(
                str(exc), context={"contract_hash": contract_hash}
            ) from exc
        plans.set_state(tenant_id, contract_hash, outcome.state)
        _audit(trail, tenant_id, outcome.audit_record)
        return TransitionResponse(contract_hash=contract_hash, state=outcome.state.value)

    # --- POST /v1/plans/{contract_hash}/execution-check ---------------------

    @app.post(
        "/v1/plans/{contract_hash}/execution-check",
        response_model=ExecutionCheckResponse,
    )
    def execution_check(
        contract_hash: str,
        tenant_id: TenantId = Depends(_require_tenant),
        plans: PlanRepository = Depends(_plan_repo),
    ) -> ExecutionCheckResponse:
        try:
            current_state = plans.get_state(tenant_id, contract_hash)
        except RepoNotFoundError as exc:
            raise PlanNotFoundError(
                f"no plan stored for contract_hash {contract_hash!r}",
                context={"contract_hash": contract_hash},
            ) from exc
        decisions = plans.get_decisions(tenant_id, contract_hash)
        approval_decision = next(
            (d.decision for d in reversed(decisions) if d.decision == "approved"), None
        )
        try:
            guard_execution(current_state, approval_decision=approval_decision)
        except ExecutionBlockedError as exc:
            raise ExecutionNotApprovedError(
                str(exc), context={"contract_hash": contract_hash}
            ) from exc
        return ExecutionCheckResponse(contract_hash=contract_hash, execution_allowed=True)

    return app


__all__ = ["create_app"]

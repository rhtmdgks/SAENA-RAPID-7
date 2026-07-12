"""FastAPI application wiring for policy-gate-service (W2A).

Routes (task instructions 2–4):
  - POST /v1/gate/plan-check — H-3 evidence policy + risk classification.
  - POST /v1/gate/authorize  — command/file/network/tool authorization.
  - GET  /v1/health          — fail-closed liveness probe (task instruction
    4); exempt from tenant-header reconciliation so a client can probe gate
    health before it has (or independent of) a resolved tenant identity.

Tenant-safe logging (task instruction 6): every route runs inside
`saena_observability.context.bind_telemetry_context("tenant", ...)` so log
lines emitted during the request (via `saena_policy_gate.service`'s
`logging.getLogger("saena_policy_gate")`) automatically carry
`saena.tenant_id` and pass through the redaction engine — no route handler
below ever interpolates a raw request body into a log message itself.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from saena_domain.identity import TenantId
from saena_domain.persistence.memory import InMemoryDecisionRecordStore
from saena_domain.persistence.ports import DecisionRecordPort
from saena_domain.policy.evidence import DiffStats
from saena_observability.context import bind_telemetry_context

from saena_policy_gate.engine import AuthorizationRequest, PolicyEngine
from saena_policy_gate.errors import PolicyGateError
from saena_policy_gate.problem import build_problem, new_trace_id
from saena_policy_gate.rules import default_engine_rules
from saena_policy_gate.schemas import (
    AuthorizeRequestBody,
    GateDecisionResponse,
    HealthResponse,
    PlanCheckRequestBody,
)
from saena_policy_gate.service import GateResult, PlanCheckInput, authorize_command, check_plan
from saena_policy_gate.tenant_middleware import TenantHeaderMiddleware

# Process-wide singletons — a single in-memory decision store/engine per
# process (SQL adapters land in w2-13; this module wires the reference
# in-memory adapter only, per this unit's persistence-reuse instruction).
_decision_store: DecisionRecordPort = InMemoryDecisionRecordStore()
_engine = PolicyEngine(default_engine_rules())


def get_decision_store() -> DecisionRecordPort:
    return _decision_store


def get_engine() -> PolicyEngine:
    return _engine


def _gate_result_to_response(result: GateResult) -> GateDecisionResponse:
    return GateDecisionResponse(
        decision=result.decision,  # type: ignore[arg-type]
        reasons=list(result.reasons),
        require_two_person=result.require_two_person,
        decision_key=list(result.decision_key),
        error_code=result.error_code,
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="policy-gate-service",
        version="0.1.0",
        description=(
            "OPA-style policy; command/file/network/tool authorization; default-deny (W2A)."
        ),
    )
    app.add_middleware(TenantHeaderMiddleware)

    @app.exception_handler(PolicyGateError)
    async def _policy_gate_error_handler(request: Request, exc: PolicyGateError) -> JSONResponse:
        tenant_id = getattr(request.state, "tenant_id", None)
        problem = build_problem(
            exc, instance=str(request.url), trace_id=new_trace_id(), tenant_id=tenant_id
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=problem,
            media_type="application/problem+json",
        )

    @app.get("/v1/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post("/v1/gate/authorize", response_model=GateDecisionResponse)
    async def authorize(
        request: Request,
        body: AuthorizeRequestBody,
        engine: Annotated[PolicyEngine, Depends(get_engine)],
        store: Annotated[DecisionRecordPort, Depends(get_decision_store)],
    ) -> GateDecisionResponse:
        tenant_id = TenantId(request.state.tenant_id)
        with bind_telemetry_context("tenant", tenant_id=tenant_id.value):
            auth_request = AuthorizationRequest(
                kind=body.kind,
                action=body.action,
                resource=body.resource,
                tenant_id=tenant_id.value,
                pipeline=body.pipeline,
            )
            result = authorize_command(
                engine=engine,
                store=store,
                tenant_id=tenant_id,
                request=auth_request,
                approver_actor_id=body.approver_actor_id,
            )
        return _gate_result_to_response(result)

    @app.post("/v1/gate/plan-check", response_model=GateDecisionResponse)
    async def plan_check(
        request: Request,
        body: PlanCheckRequestBody,
        store: Annotated[DecisionRecordPort, Depends(get_decision_store)],
    ) -> GateDecisionResponse:
        tenant_id = TenantId(request.state.tenant_id)
        with bind_telemetry_context("tenant", tenant_id=tenant_id.value):
            plan_input = PlanCheckInput(
                contract_hash=body.contract_hash,
                proposer_actor_id=body.proposer_actor_id,
                evidence_ledger_hash=body.evidence_ledger_hash,
                approved_scope=body.approved_scope,
                scope_max_globs=body.scope_max_globs,
                diff_max_files=body.diff_max_files,
                diff_max_lines=body.diff_max_lines,
                hypothesis_risks=tuple(body.hypothesis_risks),
                diff_stats=(
                    None
                    if body.diff_stats is None
                    else DiffStats(
                        files_changed=body.diff_stats.files_changed,
                        lines_changed=body.diff_stats.lines_changed,
                    )
                ),
            )
            result = check_plan(
                store=store,
                tenant_id=tenant_id,
                plan=plan_input,
                approver_actor_id=body.approver_actor_id,
            )
        return _gate_result_to_response(result)

    return app


app = create_app()

__all__ = ["app", "create_app", "get_decision_store", "get_engine"]

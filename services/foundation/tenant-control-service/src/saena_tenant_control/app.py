"""FastAPI application factory for tenant-control-service.

`create_app` takes dependency-injected ports (`TenantRepository`,
`OutboxPort`) — production callers pass the SQL adapters that land in
w2-13; tests and any pre-w2-13 caller pass
`saena_domain.persistence.InMemoryTenantRepository`/`InMemoryOutbox`
directly. No global/module-level port instance exists anywhere in this
package — every route reads its ports from FastAPI's dependency-injection
container (`app.state`), so two `create_app(...)` calls in the same process
(e.g. parallel tests) never share state.

**Exception -> RFC 9457 mapping is split across two layers, deliberately**:

1. `RequestValidationError` (FastAPI/pydantic request-body schema failures,
   e.g. an extra `namespace` field on `TenantCreateRequest`) is intercepted
   by FastAPI's own routing layer BEFORE it would ever reach
   `TenantReconciliationMiddleware.dispatch`'s `call_next` — by the time a
   validation failure could propagate as a raised exception, FastAPI's
   built-in default handler has already turned it into a plain 422
   `Response` inside `call_next`, so there is nothing left for
   `except Exception` in the middleware to catch. This module therefore
   registers its OWN `@app.exception_handler(RequestValidationError)`,
   which — unlike a route-handler exception — genuinely does run before that
   default conversion happens, and reshapes the failure into the same
   `errors.to_problem_detail` RFC 9457 body every other error on this
   service uses.
2. Every OTHER exception (domain errors from `saena_domain`, this service's
   own `TenantControlError` subclasses, or a genuinely unexpected exception)
   IS caught by `TenantReconciliationMiddleware`'s `call_next` wrapper — see
   that module's docstring "Why route-logic exceptions are also caught
   here" — because those really do propagate as raised exceptions rather
   than being pre-converted to a `Response` before reaching this layer.

`/health` is the only route outside `middleware.TENANT_SCOPED_PATH_PREFIX`
and raises nothing, so neither handler needs to cover it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from saena_domain.persistence import OutboxPort, TenantRepository
from saena_observability import bind_telemetry_context, get_logger

from saena_tenant_control.errors import (
    NamespaceInputRejectedError,
    TenantMismatchProblem,
    ValidationProblem,
    to_problem_detail,
    trace_id_for_request,
)
from saena_tenant_control.middleware import (
    RECONCILED_TENANT_STATE_KEY,
    TenantReconciliationMiddleware,
)
from saena_tenant_control.schemas import (
    TenantCreateRequest,
    TenantRecordResponse,
    TenantStatusUpdateRequest,
    TenantStatusUpdateResponse,
)
from saena_tenant_control.service import (
    create_tenant,
    get_tenant,
    get_tenant_record,
    update_tenant_status,
)

_logger = get_logger("saena_tenant_control.app")


def get_tenant_repository(request: Request) -> TenantRepository:
    repo: TenantRepository = request.app.state.tenant_repository
    return repo


def get_outbox(request: Request) -> OutboxPort:
    outbox: OutboxPort = request.app.state.outbox
    return outbox


def _require_path_tenant_matches_reconciled(request: Request, path_tenant_id: str) -> None:
    """ADR-0014 cross-tenant guard: a path `{tenant_id}` that differs from
    the header/env-reconciled tenant is denied — even though both header and
    env individually "reconciled" successfully (they agreed with each
    other), the caller is not entitled to act on a *different* tenant's
    resource than the one its own header/env pair identifies it as."""
    reconciled = getattr(request.state, RECONCILED_TENANT_STATE_KEY, None)
    if reconciled is not None and reconciled != path_tenant_id:
        raise TenantMismatchProblem(
            f"path tenant_id {path_tenant_id!r} does not match reconciled tenant {reconciled!r}",
            context={"path_tenant_id": path_tenant_id, "reconciled_tenant_id": reconciled},
        )


def create_app(repo: TenantRepository, outbox: OutboxPort) -> FastAPI:
    """Build the tenant-control-service FastAPI app.

    `repo`/`outbox` are stored on `app.state` and resolved per-request via
    `Depends(get_tenant_repository)`/`Depends(get_outbox)` — this keeps every
    route testable against an isolated port instance and matches this
    service's dependency-injected-ports architecture (task spec item 1).
    """
    app = FastAPI(title="saena-tenant-control", version="0.1.0")
    app.state.tenant_repository = repo
    app.state.outbox = outbox

    app.add_middleware(TenantReconciliationMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI intercepts RequestValidationError inside its routing layer
        # before it would ever reach TenantReconciliationMiddleware's
        # call_next as a raised exception (see module docstring) — this
        # handler is the only place that can reshape it into this service's
        # RFC 9457 problem+json shape instead of FastAPI's default 422 body.
        trace_id = trace_id_for_request(request)
        errors = exc.errors()
        problem_error: ValidationProblem
        if any(
            err.get("type") == "extra_forbidden" and err.get("loc", (None,))[-1] == "namespace"
            for err in errors
        ):
            # ADR-0014 Constraints:65 — distinct error_code for the specific
            # "caller tried to supply namespace" case (task spec: "input
            # namespace REJECTED — computed only").
            problem_error = NamespaceInputRejectedError(
                "namespace must not be supplied; it is derived from tenant_id",
                context={"errors": errors},
            )
        else:
            problem_error = ValidationProblem(
                "request failed schema validation", context={"errors": errors}
            )
        status, problem = to_problem_detail(
            problem_error, instance=str(request.url.path), trace_id=trace_id
        )
        return JSONResponse(
            status_code=status,
            content=problem.model_dump(mode="json", exclude_none=True),
            media_type="application/problem+json",
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/tenants", status_code=201)
    async def create_tenant_route(
        payload: TenantCreateRequest,
        repo: Annotated[TenantRepository, Depends(get_tenant_repository)],
    ) -> dict[str, object]:
        with bind_telemetry_context("tenant", tenant_id=payload.tenant_id):
            context = create_tenant(repo, payload)
        _logger.info(
            "tenant created",
            extra={"saena_attributes": {"saena.tenant_id": payload.tenant_id}},
        )
        return context.model.model_dump(mode="json")

    @app.get("/v1/tenants/{tenant_id}")
    async def get_tenant_route(
        tenant_id: str,
        request: Request,
        repo: Annotated[TenantRepository, Depends(get_tenant_repository)],
    ) -> dict[str, object]:
        _require_path_tenant_matches_reconciled(request, tenant_id)
        with bind_telemetry_context("tenant", tenant_id=tenant_id):
            context = get_tenant(repo, tenant_id)
        return context.model.model_dump(mode="json")

    @app.get("/v1/tenants/{tenant_id}/record", response_model=TenantRecordResponse)
    async def get_tenant_record_route(
        tenant_id: str,
        request: Request,
        repo: Annotated[TenantRepository, Depends(get_tenant_repository)],
    ) -> TenantRecordResponse:
        _require_path_tenant_matches_reconciled(request, tenant_id)
        with bind_telemetry_context("tenant", tenant_id=tenant_id):
            record = get_tenant_record(repo, tenant_id)
        return TenantRecordResponse(
            tenant_id=record.tenant_id,
            status=record.status,
            raw_payload=dict(record.raw_payload),
        )

    @app.post("/v1/tenants/{tenant_id}/status", response_model=TenantStatusUpdateResponse)
    async def update_tenant_status_route(
        tenant_id: str,
        payload: TenantStatusUpdateRequest,
        request: Request,
        repo: Annotated[TenantRepository, Depends(get_tenant_repository)],
        outbox: Annotated[OutboxPort, Depends(get_outbox)],
    ) -> TenantStatusUpdateResponse:
        _require_path_tenant_matches_reconciled(request, tenant_id)
        with bind_telemetry_context("tenant", tenant_id=tenant_id):
            previous_status, new_status = update_tenant_status(
                repo, outbox, tenant_id, payload.action
            )
        return TenantStatusUpdateResponse(
            tenant_id=tenant_id,
            previous_status=previous_status,
            status=new_status,
            action=payload.action,
        )

    return app

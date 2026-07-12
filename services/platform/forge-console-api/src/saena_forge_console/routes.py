"""Route definitions — run metadata (owned by this service per
`docs/architecture/service-catalog.md`), actor whoami, lineage passthrough
edge gate.

Permission choices (documented per task instruction 3, "pick per authz
matrix, document"):
    POST /v1/runs         -- `Permission.PROPOSE_PLAN`. Creating a run is the
                              operator-console-facing act of starting a new
                              patch-unit workflow instance — closest existing
                              permission is `propose_plan` (the proposer
                              role's defining capability, `saena_domain.
                              authz.rbac` matrix docstring); `execute_plan`
                              was considered and rejected because that
                              permission is reserved for the OPERATOR role
                              running an ALREADY-APPROVED plan (k3s §5.2
                              'runner' pool), not for originating a new run
                              record. OPEN ITEM: no ADR/contract explicitly
                              assigns run-creation to a permission — this is
                              this patch unit's own interpretation, flagged
                              in `saena_domain.authz.rbac`'s own matrix
                              docstring as inherited context.
    GET /v1/runs/{run_id}  -- `Permission.PROPOSE_PLAN` (same role family as
                              creation; a proposer must be able to read back
                              what they just created). Cross-tenant reads are
                              blocked by `RunStore`'s own tenant-isolation
                              check regardless of permission.
    GET /v1/actor/whoami   -- no permission gate (any authenticated caller,
                              i.e. any request that passes `build_request_actor`
                              at all, may read back their own identity — this
                              is an identity echo, not a privileged action).
    GET /v1/lineage/{ref}  -- `Permission.VIEW_LINEAGE`, auditor-only by
                              `saena_domain.authz.ALLOW_MATRIX` construction
                              (ADR-0013 `lineage_audit_ref` "audit role
                              전용 열람"). The runtime gate is the same
                              `require_permission`-built dependency every
                              other guarded route uses, enforced BEFORE the
                              (stubbed) downstream `LineagePort.resolve` call
                              ever runs — a non-auditor caller never reaches
                              the port at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from saena_domain.authz import Permission
from saena_domain.events import generate_uuid7
from saena_domain.identity.tenant import TENANT_ID_PATTERN

from saena_forge_console.authn import RequestActor, build_request_actor
from saena_forge_console.errors import not_found_error, validation_error
from saena_forge_console.lineage import LineagePort
from saena_forge_console.rbac import require_permission
from saena_forge_console.run_store import (
    RunNotFoundError,
    RunStore,
    RunTenantIsolationError,
)
from saena_forge_console.schemas import RunCreateRequest, RunResponse

router = APIRouter()

# Module-level dependency singletons (ruff B008: `Depends(...)` must not
# call a function directly in an argument default — `require_permission`
# builds a fresh closure per call, so each guarded route's dependency is
# built ONCE here and referenced by name at the route parameter default,
# rather than calling `require_permission(...)` inline in every signature).
_require_propose_plan = require_permission(Permission.PROPOSE_PLAN)
_require_view_lineage = require_permission(Permission.VIEW_LINEAGE)


def _require_tenant(actor: RequestActor) -> str:
    """Every run-metadata route requires a resolved `tenant_id` on the
    caller's `ActorContext` — a `system` actor invoked without one (allowed
    at the `ActorContext` construction layer) cannot own tenant-scoped run
    records, so this is a route-layer requirement on top of that already
    more permissive construction-time rule."""
    tenant_id = actor.actor.tenant_id
    if tenant_id is None or not TENANT_ID_PATTERN.fullmatch(tenant_id):
        raise validation_error(
            "tenant_id_required",
            detail="this route requires a resolved tenant_id on the caller's ActorContext",
        )
    return tenant_id


@router.post("/v1/runs", response_model=RunResponse, status_code=201)
def create_run(
    body: RunCreateRequest,
    request: Request,
    request_actor: RequestActor = Depends(_require_propose_plan),  # noqa: B008
) -> RunResponse:
    tenant_id = _require_tenant(request_actor)
    run_store: RunStore = request.app.state.run_store
    run_id = generate_uuid7()
    run = RunResponse.model_validate(
        {
            "run_id": run_id,
            "tenant_id": tenant_id,
            **body.model_dump(mode="json"),
        }
    )
    return run_store.put(tenant_id, run)


@router.get("/v1/runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: str,
    request: Request,
    request_actor: RequestActor = Depends(_require_propose_plan),  # noqa: B008
) -> RunResponse:
    tenant_id = _require_tenant(request_actor)
    run_store: RunStore = request.app.state.run_store
    try:
        return run_store.get(tenant_id, run_id)
    except RunTenantIsolationError as exc:
        # Cross-tenant access is reported as not_found, never a 403 that
        # would confirm the run_id exists under someone else's tenant
        # (information-disclosure-minimizing posture — mirrors the
        # NotFoundError/TenantIsolationError distinction domain-side, but
        # this edge deliberately projects both down to one client-facing
        # 404 rather than leaking "yes, but not yours").
        raise not_found_error(
            "resource_missing", detail="no run found for this run_id", tenant_id=tenant_id
        ) from exc
    except RunNotFoundError as exc:
        raise not_found_error(
            "resource_missing", detail="no run found for this run_id", tenant_id=tenant_id
        ) from exc


@router.get("/v1/actor/whoami")
def whoami(
    request_actor: RequestActor = Depends(build_request_actor),  # noqa: B008
) -> dict[str, object]:
    """Echo the caller's own `ActorContext` — PII-safe form (task
    instruction 3): `actor_id` and `session_id` only (the generated
    `ActorContext` schema already structurally omits
    `display_name`/`email`/`role`, contract-catalog.md:20), never logged in
    full — this route's own log line (implicit, via ASGI access logging
    outside this module) is not where the actor gets echoed at all; the
    response body is. `session_id` is included in the RESPONSE (per task
    instruction: "response may include session_id") but the
    `saena_domain.identity.ActorContext.__repr__`/`__str__` boundary this
    service relies on elsewhere never includes it — this route reads
    `session_id` via the typed property, it does not `repr()`/`str()` the
    wrapper for the response body.
    """
    actor = request_actor.actor
    return {
        "actor_id": actor.actor_id,
        "actor_type": actor.actor_type,
        "session_id": actor.session_id,
        "tenant_id": actor.tenant_id,
    }


@router.get("/v1/lineage/{ref}")
def get_lineage(
    ref: str,
    request: Request,
    request_actor: RequestActor = Depends(_require_view_lineage),  # noqa: B008
) -> dict[str, object]:
    tenant_id = _require_tenant(request_actor)
    lineage_port: LineagePort = request.app.state.lineage_port
    try:
        return lineage_port.resolve(tenant_id, ref)
    except KeyError as exc:
        raise not_found_error(
            "resource_missing", detail="no lineage record for this ref", tenant_id=tenant_id
        ) from exc


__all__ = ["router"]

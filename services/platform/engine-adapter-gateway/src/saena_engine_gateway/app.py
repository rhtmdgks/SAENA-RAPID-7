"""FastAPI application factory for `engine-adapter-gateway` (ADR-0001).

Three endpoints:

- `GET /v1/engines` — enabled adapters (enum-bound, per `AdapterRegistry`).
- `POST /v1/engines/{engine_id}/requests` — boundary check ordering:
  1. `{engine_id}` path param validated against the closed enum FIRST
     (any non-enum value → 403 `policy_denied` with an explicit "engine not
     permitted in v1" detail, before the flag or adapter is even consulted).
  2. Feature-flag check (off → 403 `policy_denied`).
  3. Adapter resolution (enum-valid + flag-on but nothing registered → 404).
  4. Payload `engine_id` (if present) must equal the path `engine_id`
     (mismatch → 400).
  5. Stub accept: `202` + echoed request id.
- `GET /v1/preflight` — gateway self-check (k3s spec §8.1 preflight flavor):
  scans the registry/flags for any adapter or enabled flag outside the v1
  closed enum and reports FAIL if one is found — defense-in-depth for
  forgectl's cluster-level preflight (w2-19) to consume, catching the case
  where something bypassed `AdapterRegistry.register`/`FlagRegistry.create`
  entirely (e.g. direct dict manipulation in a misbehaving extension).

Every error response is RFC 9457 `application/problem+json`
(`saena_engine_gateway.problem_detail`). Tenant reconciliation
(`saena_engine_gateway.tenant_middleware`) runs ahead of every non-exempt
route.

Implementation note: all route handlers and their `Depends(...)` targets are
defined at **module scope**, not as closures inside `create_app`. This
module uses `from __future__ import annotations` (PEP 563 string
annotations); FastAPI/typing resolve `Annotated[..., Depends(some_func)]`
via `typing.get_type_hints(endpoint)`, which evaluates against
`endpoint.__globals__` — a `Depends(...)` target that is only a local
closure variable (not present in the module's global namespace) fails that
lookup with a silently-swallowed `NameError`, and FastAPI falls back to
treating the parameter as an unvalidated query parameter. Per-app state
(`registry`/`flags`) is threaded through `request.app.state` instead of
closure capture, so the dependency functions can live at module scope.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from saena_observability.logging import get_logger

from saena_engine_gateway.adapters.chatgpt_search import ChatGPTSearchAdapter
from saena_engine_gateway.errors import (
    AdapterDisabledError,
    EngineGatewayError,
    EngineNotPermittedError,
    PayloadEngineMismatchError,
)
from saena_engine_gateway.flags import FlagRegistry
from saena_engine_gateway.problem_detail import build_problem_detail
from saena_engine_gateway.registry import PERMITTED_ENGINE_IDS, AdapterRegistry
from saena_engine_gateway.tenant_middleware import TenantReconciliationMiddleware

_logger = get_logger("saena_engine_gateway")


class EngineRequestBody(BaseModel):
    """Request body for `POST /v1/engines/{engine_id}/requests`.

    `engine_id` is optional — a caller may omit it and rely on the path
    parameter alone. When present, it must equal the path `engine_id`
    (`PayloadEngineMismatchError` otherwise). `extra="allow"` because the
    v1 gateway is a boundary-enforcement stub, not the real observation
    request contract (W4 owns that schema) — this endpoint accepts an
    arbitrary JSON object today and only inspects the one field it must
    validate.
    """

    model_config = ConfigDict(extra="allow")

    engine_id: str | None = None


def _default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(ChatGPTSearchAdapter())
    return registry


def _default_flags() -> FlagRegistry:
    flags = FlagRegistry()
    flags.create("chatgpt-search", enabled=True)
    return flags


def get_registry(request: Request) -> AdapterRegistry:
    """FastAPI dependency: the `AdapterRegistry` bound to this app instance
    (`request.app.state.registry`, set by `create_app`)."""
    registry_obj = request.app.state.registry
    assert isinstance(registry_obj, AdapterRegistry)
    return registry_obj


def get_flags(request: Request) -> FlagRegistry:
    """FastAPI dependency: the `FlagRegistry` bound to this app instance
    (`request.app.state.flags`, set by `create_app`)."""
    flags_obj = request.app.state.flags
    assert isinstance(flags_obj, FlagRegistry)
    return flags_obj


RegistryDep = Annotated[AdapterRegistry, Depends(get_registry)]
FlagsDep = Annotated[FlagRegistry, Depends(get_flags)]


async def list_engines(registry_dep: RegistryDep, flags_dep: FlagsDep) -> dict[str, Any]:
    """Enabled adapters, enum-bound. An `engine_id` appears only if it is
    both registered AND flag-enabled — a registered-but-disabled adapter is
    intentionally omitted (this endpoint answers "what can I call right
    now", not "what exists")."""
    enabled = [
        engine_id
        for engine_id in registry_dep.enabled_engine_ids()
        if flags_dep.is_enabled(engine_id)
    ]
    return {"engines": enabled}


async def submit_engine_request(
    engine_id: str,
    body: EngineRequestBody,
    registry_dep: RegistryDep,
    flags_dep: FlagsDep,
) -> dict[str, Any]:
    # 1. Closed-enum boundary check FIRST — before flag/adapter lookup, so a
    #    non-enum engine_id always fails the same way regardless of
    #    registry/flag state.
    if engine_id not in PERMITTED_ENGINE_IDS:
        raise EngineNotPermittedError(engine_id)

    # 2. Feature-flag check.
    if not flags_dep.is_enabled(engine_id):
        raise AdapterDisabledError(engine_id)

    # 3. Adapter resolution.
    adapter = registry_dep.get(engine_id)

    # 4. Payload/path engine_id agreement.
    if body.engine_id is not None and body.engine_id != engine_id:
        raise PayloadEngineMismatchError(engine_id, body.engine_id)

    # 5. Stub accept.
    request_id = str(uuid.uuid4())
    payload = body.model_dump(exclude_none=True)
    stub_result = adapter.submit_observation_request(payload)
    return {
        "request_id": request_id,
        "engine_id": engine_id,
        "status": "accepted",
        "echo": stub_result,
    }


async def preflight(registry_dep: RegistryDep, flags_dep: FlagsDep) -> dict[str, Any]:
    """Gateway self-check per k3s spec §8.1 preflight flavor: "preflight
    must fail if... engine flags include any Google AI service in v1".

    Scans `enabled_engine_ids()`/`flagged_engine_ids()` — both deliberately
    bypass the enum-guarded `get`/`is_enabled` accessors (which would
    themselves raise before this endpoint could report anything) — for any
    `engine_id` outside `PERMITTED_ENGINE_IDS`. Reachable without a tenant
    context (`tenant_middleware._TENANT_EXEMPT_PATHS`) since forgectl
    invokes this ahead of any per-tenant request.
    """
    rogue_adapters = [
        engine_id
        for engine_id in registry_dep.enabled_engine_ids()
        if engine_id not in PERMITTED_ENGINE_IDS
    ]
    rogue_flags = [
        engine_id
        for engine_id in flags_dep.flagged_engine_ids()
        if engine_id not in PERMITTED_ENGINE_IDS
    ]
    rogue = sorted(set(rogue_adapters) | set(rogue_flags))
    status = "FAIL" if rogue else "PASS"
    return {
        "status": status,
        "permitted_engine_ids": sorted(PERMITTED_ENGINE_IDS),
        "rogue_engine_ids": rogue,
    }


async def _engine_gateway_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, EngineGatewayError)
    body = build_problem_detail(exc, instance=str(request.url.path))
    _logger.info(
        "engine_gateway_error error_code=%s status=%s",
        exc.error_code,
        exc.http_status,
    )
    return JSONResponse(body, status_code=exc.http_status, media_type="application/problem+json")


def create_app(
    *,
    registry: AdapterRegistry | None = None,
    flags: FlagRegistry | None = None,
) -> FastAPI:
    """Build the `engine-adapter-gateway` FastAPI application.

    `registry`/`flags` default to a v1-standard setup (ChatGPT Search
    registered and enabled) but are injectable so tests can exercise
    flag-off, rogue-adapter, and empty-registry scenarios without module-
    level global state.
    """
    resolved_registry = registry if registry is not None else _default_registry()
    resolved_flags = flags if flags is not None else _default_flags()

    app = FastAPI(title="engine-adapter-gateway", version="0.1.0")
    app.state.registry = resolved_registry
    app.state.flags = resolved_flags
    app.add_middleware(TenantReconciliationMiddleware)
    app.add_exception_handler(EngineGatewayError, _engine_gateway_error_handler)

    app.get("/v1/engines")(list_engines)
    app.post("/v1/engines/{engine_id}/requests", status_code=202)(submit_engine_request)
    app.get("/v1/preflight")(preflight)

    return app

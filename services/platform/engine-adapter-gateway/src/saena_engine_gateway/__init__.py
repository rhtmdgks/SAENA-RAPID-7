"""saena_engine_gateway — engine-adapter-gateway (ADR-0001 option A).

Physical boundary between SAENA's tenant-facing services and per-engine
provider adapters. ADR-0001 confirms option A: adapters are gateway-embedded
library units (`packages/provider-adapters/*`), not independent
microservices; feature-flag granularity is one flag per adapter unit, and
this gateway is the single control point through which any engine may be
reached.

v1 scope (CLAUDE.md "Engine scope (v1)"): **ChatGPT Search only**. Google AI
Overviews, Google AI Mode, and Gemini are disabled — optimize/observe/claim
against those engines is forbidden. `engine_id` is a closed enum
(`saena_schemas.common.engine_id_v1.EngineId`, generated from
`packages/contracts/json-schema/common/engine-id/v1/engine-id.schema.json`,
ADR-0013 §Current decision) with exactly one v1 member: `"chatgpt-search"`.
Every boundary in this package — adapter registration, feature-flag
creation, and the HTTP API — rejects any other value at construction/request
time, never merely at response-shaping time (defense-in-depth per k3s spec
§8.1 preflight: "engine flags include any Google AI service in v1" is a
FAIL condition).

Public API:
    EngineAdapter          — Protocol every v1/vNext adapter implements.
    AdapterRegistry         — construction-time closed-enum-validated registry.
    ChatGPTSearchAdapter    — the single v1 adapter.
    AdapterFlag             — per-adapter feature-flag value object.
    FlagRegistry            — construction-time closed-enum-validated flag store.
    EngineGatewayError      — base exception for this package.
    EngineNotPermittedError — engine_id outside the v1 closed enum.
    AdapterNotFoundError    — engine_id valid but no adapter registered.
    AdapterDisabledError    — engine_id valid, adapter registered, flag off.
    PayloadEngineMismatchError — request body engine_id != path engine_id.
    create_app              — FastAPI application factory.
"""

from __future__ import annotations

from saena_engine_gateway.adapters.chatgpt_search import ChatGPTSearchAdapter
from saena_engine_gateway.app import create_app
from saena_engine_gateway.errors import (
    AdapterDisabledError,
    AdapterNotFoundError,
    EngineGatewayError,
    EngineNotPermittedError,
    PayloadEngineMismatchError,
)
from saena_engine_gateway.flags import AdapterFlag, FlagRegistry
from saena_engine_gateway.registry import AdapterRegistry, EngineAdapter

__all__ = [
    "AdapterDisabledError",
    "AdapterFlag",
    "AdapterNotFoundError",
    "AdapterRegistry",
    "ChatGPTSearchAdapter",
    "EngineAdapter",
    "EngineGatewayError",
    "EngineNotPermittedError",
    "FlagRegistry",
    "PayloadEngineMismatchError",
    "create_app",
]

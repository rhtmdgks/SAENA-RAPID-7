# engine-adapter-gateway

| Field | Value |
|---|---|
| Service name | `engine-adapter-gateway` |
| Bounded context | Provider/engine adapter boundary |
| Primary responsibility | provider adapter contract, feature flags, rate limits |
| Owned data | adapter config |
| Consumed contracts | engine-scoped observation/optimization requests |
| Published events | adapter.config.updated.v1 (PROPOSED) |
| Consumed events | — |
| Upstream dependencies | — (engine boundary edge; adapter 구현 코드 의존은 `packages/provider-adapters/*` — dependency-policy.md 소관, 런타임 upstream 아님) |
| Downstream consumers | chatgpt-observer-service; future engine consumers |
| Security boundary | v1: chatgpt-search ON; google/gemini feature flag OFF / scale 0 |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **v1 boundary-enforcement gateway implemented (w2-17)** |

## Implementation (w2-17)

`saena_engine_gateway` (`src/saena_engine_gateway/`) — FastAPI app implementing
ADR-0001 option A (adapters as gateway-embedded library units, physically
separate from observer business logic) and the CLAUDE.md v1 engine scope
(ChatGPT Search only; Google AI Overviews/AI Mode/Gemini disabled).

- `registry.py` — `EngineAdapter` Protocol + `AdapterRegistry`. Registration
  is validated at construction time against the closed `engine_id` enum
  (`saena_schemas.common.engine_id_v1.EngineId`, generated from
  `packages/contracts/json-schema/common/engine-id/v1/engine-id.schema.json`,
  ADR-0013) — a non-enum `engine_id` raises `EngineNotPermittedError` at
  `register()`, never merely at request time.
- `flags.py` — `FlagRegistry`/`AdapterFlag`, one flag per adapter unit
  (ADR-0001 flag-granularity decision). Flags for non-enum engines cannot be
  created at all.
- `adapters/chatgpt_search.py` — `ChatGPTSearchAdapter`, the single v1
  adapter. Deterministic boundary-enforcement stub; real observation
  methodology is chatgpt-observer-service's W4 scope.
- `app.py` — `create_app()` factory: `GET /v1/engines`,
  `POST /v1/engines/{engine_id}/requests`, `GET /v1/preflight` (k3s spec
  §8.1 preflight flavor — FAILs if a rogue non-enum adapter/flag is present).
- `tenant_middleware.py` — ADR-0014 synchronous HTTP tenant reconciliation
  (`X-Saena-Tenant-Id` vs `SAENA_TENANT_ID`), tenant-safe structured logging
  via `saena_observability`.
- `errors.py` / `problem_detail.py` — ADR-0015 RFC 9457
  `application/problem+json` error model, covering every response path this
  app can return: `EngineGatewayError` subclasses, FastAPI/pydantic request
  validation failures (no `input`/`ctx` value echo — sanitized to
  `loc`/`type`/`msg` only), and any other unhandled exception (fixed
  `detail`, no stack trace).

Not yet implemented (out of this patch unit's scope): real ChatGPT Search
observation calls, citation normalization, rate limiting beyond flag
on/off, `adapter.config.updated.v1` event publication, Dockerfile/Helm
deployment wiring.

## Source specification references

- `docs/decisions/ADR-0001-google-gemini-adapter-deployment-shape.md`
- `docs/decisions/ADR-0013-event-envelope-v1.md` (closed `engine_id` enum)
- `docs/decisions/ADR-0014-tenant-propagation.md`
- `docs/decisions/ADR-0015-canonical-error-model.md`
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4, §8.1
- CLAUDE.md "Engine scope (v1)"

## Status

v1 boundary-enforcement gateway implemented (w2-17): adapter registry,
per-adapter feature flags, and the 3-endpoint HTTP surface are in place and
verified (`uv run just verify` green, 100% diff coverage). Dockerfile/Helm
deployment artifacts and the real ChatGPT Search observation implementation
remain NOT IMPLEMENTED (W4+/deploy-track scope).

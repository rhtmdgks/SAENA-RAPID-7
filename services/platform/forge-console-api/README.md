# forge-console-api

| Field | Value |
|---|---|
| Service name | `forge-console-api` |
| Bounded context | B-department operator API/UI backend |
| Primary responsibility | B부서 UI, RBAC, run 생성·승인 |
| Owned data | run metadata |
| Consumed contracts | operator commands; approval actions |
| Published events | run.created.v1 (PROPOSED); approval events |
| Consumed events | plan.contract.*; quality.gate.*; handoff-ready signals |
| Upstream dependencies | operator-console (apps) |
| Downstream consumers | tenant-control-service; repository-intake-service; plan-contract-service |
| Security boundary | RBAC; no production deploy credentials |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **PARTIAL (W2A)** — v1 edge (AuthN stub, RBAC, tenant boundary, run metadata) implemented; see Status below |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- ADR-0007 (v1 sole edge), ADR-0014 (tenant propagation), ADR-0015 (canonical
  error model), ADR-0016 (telemetry conventions)

## Status

**PARTIAL (W2A, unit w2-12-forge-console)** — this service is the v1 sole
edge (ADR-0007 D-4: `apps/api-gateway` is FUTURE/SaaS). Implemented in this
patch unit:

- **AuthN stub**: `X-Saena-Actor-Id` / `X-Saena-Session-Id` /
  `X-Saena-Actor-Type` / `X-Saena-Tenant-Id` / `X-Saena-Roles` headers ->
  `saena_domain.identity.ActorContext` construction and validation (real —
  including the human-actor-requires-tenant_id conditional). A real identity
  provider (OIDC/JWT verification, session issuance) is **W3+**, not yet
  implemented — no signature verification happens here.
- **RBAC**: route-level `saena_domain.authz.authorize()` dependency,
  default-deny. Permission-to-route mapping is documented (and flagged as
  this patch unit's own interpretation where no ADR/contract dictates it) in
  `src/saena_forge_console/routes.py`'s module docstring.
- **Tenant boundary**: `X-Saena-Tenant-Id` <-> pod env `SAENA_TENANT_ID`
  reconciliation middleware (ADR-0014) — 403 + structured audit-shaped log
  on mismatch.
- **RFC 9457 `problem+json`** error responses (ADR-0015 taxonomy), including
  FastAPI's own request-validation 422s.
- **Trace**: W3C `traceparent` accept/generate + response-header
  propagation, `saena_observability` structured single-line JSON logs
  (ADR-0016).
- **Endpoints**: `POST /v1/runs`, `GET /v1/runs/{run_id}` (run metadata —
  owned by this service per `docs/architecture/service-catalog.md`, backed
  by a process-local in-memory store keyed `(tenant_id, run_id)`),
  `GET /v1/actor/whoami` (PII-safe `ActorContext` echo), `GET /v1/lineage/{ref}`
  (auditor-only edge gate; downstream audit-ledger resolution is an injected
  `LineagePort` STUB in this patch unit, not a real client — see
  `src/saena_forge_console/lineage.py`).

**NOT yet implemented** (explicitly out of this patch unit's scope):

- Real identity provider / token verification (W3+).
- Real downstream `LineagePort` client (audit-ledger-service HTTP/RPC) — no
  cross-service imports are permitted from this patch unit's exclusive-write
  paths; only local port injection.
- Durable run-metadata storage (SQL adapter) — the current `RunStore` is
  pure in-memory, process-local, no persistence across restarts.
- Published events (`run.created.v1`) — this patch unit does not publish to
  the outbox; run creation only writes to the local `RunStore`.
- Consumed events (`plan.contract.*`, `quality.gate.*`, handoff-ready
  signals) — no event consumer is wired in this patch unit.
- Dockerfile / k3s deployment manifests.

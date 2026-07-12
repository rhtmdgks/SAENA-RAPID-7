# tenant-control-service

| Field | Value |
|---|---|
| Service name | `tenant-control-service` |
| Bounded context | Tenancy, policy profile, retention |
| Primary responsibility | tenant isolation, policy profile, retention |
| Owned data | tenant policy |
| Consumed contracts | tenant onboarding commands; policy update requests |
| Published events | tenant.policy.updated.v1 (PROPOSED — **not published by this unit**, see Implementation status) |
| Consumed events | — (OPEN DECISION for intake events) |
| Upstream dependencies | forge-console-api |
| Downstream consumers | all tenant-scoped services |
| Security boundary | tenant boundary; no cross-tenant reads |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `foundation` |
| Implementation status | **W2A PARTIAL** — FastAPI HTTP API + in-memory persistence (w2-08). SQL adapters land in w2-13. |

## API surface (w2-08)

All routes are served by `saena_tenant_control.create_app(repo, outbox)`
(dependency-injected `saena_domain.persistence.TenantRepository`/`OutboxPort`
ports — production callers pass w2-13's SQL adapters, tests/pre-w2-13
callers pass `InMemoryTenantRepository`/`InMemoryOutbox`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness (no tenant scoping). |
| POST | `/v1/tenants` | Create a tenant. `namespace` is server-derived from `tenant_id` (ADR-0014); a request that supplies `namespace` is rejected. |
| GET | `/v1/tenants/{tenant_id}` | Gated read — 403 problem for `suspended`/`terminating` tenants. |
| GET | `/v1/tenants/{tenant_id}/record` | Gate-free admin/status view — works for suspended/terminating tenants. |
| POST | `/v1/tenants/{tenant_id}/status` | Apply a `suspend`/`reactivate`/`terminate` transition. |

Every `/v1/tenants/...` route is reconciled against `X-Saena-Tenant-Id`
(header) vs. `SAENA_TENANT_ID` (pod env) per ADR-0014 — a mismatch, or a
path `tenant_id` that disagrees with the reconciled tenant, is rejected with
an RFC 9457 (ADR-0015) `application/problem+json` 403 response. Every error
response on this service (validation, not-found, conflict, policy-denied,
tenant-mismatch, internal) uses that same RFC 9457 shape; no stack traces or
raw exception text ever reach a response body.

**Why `tenant.policy.updated.v1` is not published**: it remains a
**PROPOSED** (unconfirmed) topic — it does not appear in the CONFIRMED v1
AsyncAPI catalog. Publishing it would require either bypassing
`EnvelopeFactory`'s topic-catalog check or asserting a not-yet-approved
topic into `packages/contracts` from this services-layer patch unit (a
single-owner path this unit does not touch). Status-change decisions are
instead returned directly in the `POST .../status` response body and
recorded via a structured log line — see `saena_tenant_control.service`
module docstring for the full reasoning.

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- ADR-0014 (tenant propagation), ADR-0015 (canonical error model)

## Status

**W2A PARTIAL** (w2-08) — FastAPI HTTP API + in-memory persistence
(`saena_domain.persistence.InMemoryTenantRepository`/`InMemoryOutbox`) behind
dependency-injected ports. SQL adapters (real persistence) land in w2-13;
this unit ships no SQL, no Kafka/Redpanda bus wiring, and does not publish
any event (see "Why `tenant.policy.updated.v1` is not published" above).

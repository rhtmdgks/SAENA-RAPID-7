# audit-ledger-service

| Field | Value |
|---|---|
| Service name | `audit-ledger-service` |
| Bounded context | Immutable audit trail |
| Primary responsibility | append-only run/event/hash chain; evidence bundle integrity |
| Owned data | audit log |
| Consumed contracts | run events; approval events; quality results |
| Published events | audit.event.appended.v1 (PROPOSED) |
| Consumed events | plan.contract.*; patch.unit.*; quality.gate.*; experiment.outcome.* |
| Upstream dependencies | all planes |
| Downstream consumers | forge-console-api; compliance consumers |
| Security boundary | append-only; immutable role access |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `foundation` |
| Implementation status | **IMPLEMENTED (W2A) — FastAPI app, in-memory reference ledger, no persistence/bus wiring** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- `docs/architecture/contract-catalog.md` — AuditEvent row (Owner audit-ledger, Idempotency key "event hash (chain)")
- ADR-0013 (`lineage_audit_ref` audit-role-only)
- ADR-0015 (canonical error model / `AuditEvent` error footprint)

## API surface (w2-10)

`saena_audit_ledger.create_app(ledger: AuditLedgerPort) -> FastAPI`:

| Method | Path | RBAC permission | Notes |
|---|---|---|---|
| POST | `/v1/audit/entries` | `append_audit` | Body excludes `event_hash`/`prev_event_hash` — service computes both via `saena_domain.audit.build_entry`; forbidden-data guard runs before hashing |
| GET | `/v1/audit/entries` | `read_audit` | Tenant-scoped via `X-Saena-Tenant-Id`; omit header for system-scope chain |
| GET | `/v1/audit/verify` | `read_audit` | `{ok, first_broken_index}` — mirrors `saena_domain.audit.verify_chain` |
| GET | `/v1/audit/lineage/{lineage_ref}` | `view_lineage` (**auditor role only**, ADR-0013) | Resolves an opaque `audit:sha256:<hex>` ref within the chain identified by the request's own tenant scope |
| PUT/DELETE | `/v1/audit/entries` | — | Always 405 — no mutation route exists (append-only by route-table shape, not just by convention) |

## Documented W2A scope boundaries

- **AuthN stub**: caller roles are read from `X-Saena-Roles` (comma-separated), an UNVERIFIED transport header — nothing in this process checks the header's claims against a real identity (mTLS cert, JWT, session). The RBAC *decision* itself is real: `saena_domain.authz.authorize`'s default-deny allow matrix, unchanged from every other consumer of that module. Real authN is W3+ scope.
- **`audit.event.appended.v1` is a PROPOSED topic** — no outbox publish on append; a structured log line is emitted instead as an operational breadcrumb. Wiring to `OutboxPort`/the bus is out of this unit's scope (`saena_domain.persistence` module docstring: "이벤트는 transactional outbox 기록까지 — bus 배선은 2C").
- **Persistence**: bound to whatever `AuditLedgerPort` implementation the caller injects into `create_app`; this unit ships no SQL adapter (`InMemoryAuditLedger`, `saena_domain.persistence`, is the only concrete adapter available pre-w2-13).

## Status

IMPLEMENTED (W2A, w2-10) — FastAPI app factory + RFC 9457 problem+json errors +
RBAC boundary, backed by the in-memory reference `AuditLedgerPort` adapter.
No Dockerfile/k3s manifest yet (deploy tooling out of this patch unit's
scope). Unit tests: `tests/unit/svc_audit_ledger/`.

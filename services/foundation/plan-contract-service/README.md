# plan-contract-service

| Field | Value |
|---|---|
| Service name | `plan-contract-service` |
| Bounded context | Action Contract lifecycle |
| Primary responsibility | Plan Mode results → Action Contract structure/validation; propose→approve state |
| Owned data | action contracts |
| Consumed contracts | plan drafts; evidence IDs; patch unit candidates |
| Published events | plan.contract.proposed.v1; plan.contract.approved.v1 |
| Consumed events | intervention candidates; discovery/demand/claim artifacts (PROPOSED) |
| Upstream dependencies | intervention-generator-service; forge-console-api; portfolio-optimizer-service (선택 포트폴리오 소비 — 2026-07-12 감사 정합화) |
| Downstream consumers | agent-orchestrator-service; policy-gate-service |
| Security boundary | human-approval-gated; signed contract immutability |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `foundation` |
| Implementation status | **IMPLEMENTED (w2-11) — FastAPI HTTP surface, in-process test doubles** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- `docs/decisions/ADR-0003-approval-transition-authority-path.md` (approval authority order)
- `docs/decisions/ADR-0024-w1-contract-deviations.md` (e) — `plan.contract.approved.v1` payload excludes `approver_actor_id`
- `docs/architecture/security-model.md` H-3, H-7, "policy-gate = fail-closed"

## Status

**IMPLEMENTED (w2-11)** — `saena_plan_contract.create_app()` FastAPI factory over
`saena_domain.policy`/`saena_domain.persistence` (w2-05/w2-07). Endpoints:
`POST /v1/plans` (propose), `POST /v1/plans/{contract_hash}/decisions` (ADR-0003
order: Policy Gate pre-check → `transition()` → approved-event/lease issuance),
`POST /v1/plans/{contract_hash}/cancel`, `POST /v1/plans/{contract_hash}/expire`,
`GET /v1/plans/{contract_hash}`, `POST /v1/plans/{contract_hash}/execution-check`.

**NOT IMPLEMENTED / OPEN ITEMS (honest gaps, not silently deferred):**

- `policy-gate-service` itself does not exist yet (that service's own README:
  NOT IMPLEMENTED) — `PolicyGateClient` is a locally-defined port
  (`gate_client.py`: `Protocol` + `HttpPolicyGateClient` (httpx) +
  `FakeGateClient`); `HttpPolicyGateClient`'s `{base_url}/v1/plan-check` /
  `/health` request shape is this client's own forward-declared expectation,
  not yet cross-validated against a real policy-gate-service implementation.
- `contract_hash` canonicalization (`contract_hash.py`) reuses
  `saena_domain.audit.canonical.canonical_json`/`sha256_hex` as an INTERIM
  substitute for the not-yet-written JCS (RFC 8785) ADR that
  `change-plan.schema.json`'s own `$comment` flags as pre-W2A OPEN — this is
  NOT guaranteed byte-identical to whatever that ADR eventually mandates.
- Persistence is the w2-07 in-memory reference adapters only
  (`InMemoryPlanRepository`/`InMemoryOutbox`) — SQL adapters land in w2-13,
  the Kafka/Redpanda bus publisher lands in w2-18 (outbox recording only here,
  per `saena_domain.persistence` module scope).
- Temporal signal dispatch (ADR-0003 step 3, "plan-contract-service가
  Temporal signal 직발") is NOT implemented — this unit stops at APPROVED +
  lease issuance + outbox-recorded `plan.contract.approved.v1`
  (notification-only per ADR-0003); wiring an actual Temporal client call is
  out of this patch unit's scope.
- Per-patch-unit lease records (`saena_domain.policy.issue_lease`) are
  constructed on approval but not persisted/exposed by any endpoint in this
  unit — value-object construction only, matching that function's own scope
  note.
- The audit trail (`audit_trail.py`) is this service's own in-process,
  per-app-instance `AuditTrailRecord` buffer, NOT a call into
  `audit-ledger-service` (services must not import each other; no HTTP
  client to that service exists yet either) — real hash-chain persistence is
  a future integration point.

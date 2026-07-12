# policy-gate-service

| Field | Value |
|---|---|
| Service name | `policy-gate-service` |
| Bounded context | Authorization / policy-as-code |
| Primary responsibility | OPA-style policy; command/file/network/tool authorization |
| Owned data | signed policy decisions |
| Consumed contracts | Action Contract; tool/file/network requests |
| Published events | policy.decision.recorded.v1 (PROPOSED — not yet in the CONFIRMED AsyncAPI catalog; decisions recorded via `DecisionRecordPort` + structured log, not the outbox, until promoted) |
| Consumed events | plan.contract.approved.v1 |
| Upstream dependencies | agent-orchestrator-service; agent-runner-service |
| Downstream consumers | agent-runner-service; audit-ledger-service |
| Security boundary | default-deny; least privilege |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `foundation` |
| Implementation status | **PARTIAL (W2A)** — default-deny policy engine, fail-closed HTTP surface, in-memory decision recording. No Dockerfile/Helm chart, no SQL persistence adapter (w2-13), no real event bus wiring (w2-18), no signed/bundled rule set. |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- `docs/decisions/ADR-0003-approval-transition-authority-path.md` (Policy Gate pre-verification role in the approval authority path)
- `docs/decisions/ADR-0015-canonical-error-model.md` (`policy_denied.gate_unavailable` fail-closed case; RFC 9457 problem+json)
- `docs/architecture/security-model.md` (H-3 evidence anchoring, H-7 two-person approval, "policy-gate = fail-closed")
- `docs/architecture/implementation-waves.md` W2A exit criteria

## Status

**PARTIAL (W2A, this patch unit w2-09-policy-gate)**:

- `saena_policy_gate.engine` — default-deny `PolicyEngine` over a data-driven
  `AllowRule` allowlist; argv-level command classification (`classify_command`,
  `classify_pipeline`) closes the named deny-bypass regressions (`kubectl
  patch`/`edit`/`delete`/`replace`, `git push` incl. `git -c a=b push` / `git
  -C dir push` / flag-injected forms, `helm upgrade`/`install`/`uninstall`/
  `delete`, `curl|sh`-shaped pipelines, absolute-path `argv[0]`, tab/multi-space
  whitespace tricks).
- `saena_policy_gate.service` — fail-closed orchestration (`GateUnavailableError`
  / `saena.policy_denied.gate_unavailable` on ANY engine/H-3-evaluator
  exception), H-3 evidence-policy plan-check (`saena_domain.policy.
  evaluate_h3_evidence_policy`), risk classification
  (`is_high_risk_plan` → `require_two_person`), idempotent decision recording
  via `saena_domain.persistence.DecisionRecordPort` (in-memory reference
  adapter only — SQL lands in w2-13).
- `saena_policy_gate.app` — FastAPI surface: `POST /v1/gate/plan-check`,
  `POST /v1/gate/authorize`, `GET /v1/health` (exempt from tenant-header
  reconciliation, for fail-closed client-side liveness probing); RFC 9457
  `application/problem+json` error mapping (ADR-0015); `X-Saena-Tenant-Id`
  reconciliation middleware (`saena_domain.identity.http.reconcile_tenant`
  pattern).
- `policy.decision.recorded.v1` is NOT published to the outbox — it is a
  PROPOSED topic, absent from the CONFIRMED v1 AsyncAPI catalog
  (`packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml`); every
  decision is instead persisted via `DecisionRecordPort` plus a tenant-safe
  structured log line (see `saena_policy_gate.service` module docstring).

Not yet implemented: Dockerfile/Helm chart, real SQL persistence (w2-13),
event bus publishing (w2-18), a signed/versioned production rule bundle
(k3s spec §8.4 "policy bundle defect" rollback — `saena_policy_gate.rules`
ships a small reference allowlist only), RBAC-gated route authorization
(`saena_domain.authz` exists but is not yet wired into this service's
routes).

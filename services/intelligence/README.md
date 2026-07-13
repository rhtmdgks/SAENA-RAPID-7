# services/intelligence

## Purpose

Bounded-context area for SAENA FORGE microservices classified under `intelligence`.

## Scope

Service directories listed below. Wave 4 (Intelligence) P0 modules IMPLEMENTED:

- `demand-graph-service` (`saena_demand_graph`, w4-02) — first-party query-cluster
  (demand graph) builder → emits `demand.graph.versioned.v1`.
- `entity-resolution-service` (`saena_entity_resolution`, w4-03) — tenant-scoped
  alias canonicalization → emits `entity.graph.versioned.v1`.
- `claim-evidence-service` (`saena_claim_evidence`, w4-04 + QEEG read-projection
  w4-11) — atomic claim/evidence ledger (fail-closed publishability) →
  emits `claim.evidence.versioned.v1`.
- `citation-intelligence-service` (`saena_citation_intelligence`, w4-05) — URL
  normalization + ownership classification → emits `citation.normalized.v1`.
- `absorption-analysis-service` — P1, OUT OF WAVE 4 SCOPE (not implemented).

## Intelligence-worker boundary (w4-12)

The four P0 services are independent bounded contexts. Their ONLY cross-service
coupling is published contracts (events on the AsyncAPI bus / HTTP), never a
direct code import — enforced structurally by the `services-are-independent`
import-linter contract (`.importlinter`), which lists all four `saena_*`
intelligence modules. A service that `import`ed a sibling would break `just
verify`.

The **intelligence-worker** runtime is the deployment-level orchestration
(w4-14 Helm `intelligence-worker` workload) that runs these services as
event-driven consumers/producers over the shared bus. It carries no
orchestration logic of its own beyond wiring: each service owns its own
determinism, tenant-scoping, engine-scope (chatgpt-search only), and
fail-closed guards. No shared mutable state, no shared DB table, no direct
service-to-service call path exists.

## Constraints

- No shared DB table direct access across services
- Own schema/DB per service
- Contract/event first
- Service-to-service boundary = published events/HTTP only (import-linter
  `services-are-independent`, enforced)

## Open decisions

See `docs/architecture/service-catalog.md`.

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3

## Status

WAVE 4 P0 IMPLEMENTED (demand-graph, entity-resolution, claim-evidence,
citation-intelligence + QEEG projection). Boundary enforced by
`services-are-independent` (11 import-linter contracts KEPT). absorption-analysis
(P1) NOT IMPLEMENTED (out of Wave 4 scope).

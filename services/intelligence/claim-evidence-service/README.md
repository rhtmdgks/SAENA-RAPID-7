# claim-evidence-service

| Field | Value |
|---|---|
| Service name | `claim-evidence-service` |
| Bounded context | Claim–evidence ledger |
| Primary responsibility | claim extraction, evidence ledger, freshness/legal status |
| Owned data | claim/evidence graph |
| Consumed contracts | source-of-truth; site assets |
| Published events | claim.evidence.versioned.v1 (PROPOSED) |
| Consumed events | site.inventory.completed.v1; demand.graph.versioned.v1; entity.graph.versioned.v1 (PROPOSED — 2026-07-12 감사: upstream 선언과 정합화) |
| Upstream dependencies | entity-resolution-service; site-discovery-service |
| Downstream consumers | intervention-generator-service; quality-eval-service |
| Security boundary | unsupported claim = release-blocking; no fabricated evidence |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `intelligence` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

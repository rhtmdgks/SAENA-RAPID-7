# entity-resolution-service

| Field | Value |
|---|---|
| Service name | `entity-resolution-service` |
| Bounded context | Entity canonicalization |
| Primary responsibility | brand/product/integration/competitor canonicalization |
| Owned data | entity graph |
| Consumed contracts | query clusters; site inventory; source-of-truth |
| Published events | entity.graph.versioned.v1 (PROPOSED) |
| Consumed events | demand.graph.versioned.v1 |
| Upstream dependencies | demand-graph-service |
| Downstream consumers | claim-evidence-service; citation-intelligence-service |
| Security boundary | tenant-scoped entity ownership |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `intelligence` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

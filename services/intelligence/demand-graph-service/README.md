# demand-graph-service

| Field | Value |
|---|---|
| Service name | `demand-graph-service` |
| Bounded context | Query / demand graph |
| Primary responsibility | first-party query·sales·support·site search → question graph |
| Owned data | query clusters |
| Consumed contracts | first-party approved materials |
| Published events | demand.graph.versioned.v1 |
| Consumed events | site.inventory.completed.v1 |
| Upstream dependencies | site-discovery-service |
| Downstream consumers | entity-resolution-service; intervention-generator-service |
| Security boundary | tenant-partitioned; no PII in events |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `intelligence` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

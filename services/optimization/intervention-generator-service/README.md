# intervention-generator-service

| Field | Value |
|---|---|
| Service name | `intervention-generator-service` |
| Bounded context | Intervention / hypothesis generation |
| Primary responsibility | 다중 가설과 patch unit 후보 생성 |
| Owned data | intervention candidates |
| Consumed contracts | QEEG artifacts; site inventory; observation gaps |
| Published events | intervention.candidates.ready.v1 (PROPOSED) |
| Consumed events | demand.graph.versioned.v1; claim.evidence.versioned.v1; citation.normalized.v1 |
| Upstream dependencies | intelligence + acquisition services |
| Downstream consumers | plan-contract-service; portfolio-optimizer-service |
| Security boundary | evidence gate; no unsupported public claims |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `optimization` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

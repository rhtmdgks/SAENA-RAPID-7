# tenant-control-service

| Field | Value |
|---|---|
| Service name | `tenant-control-service` |
| Bounded context | Tenancy, policy profile, retention |
| Primary responsibility | tenant isolation, policy profile, retention |
| Owned data | tenant policy |
| Consumed contracts | tenant onboarding commands; policy update requests |
| Published events | tenant.policy.updated.v1 (PROPOSED) |
| Consumed events | — (OPEN DECISION for intake events) |
| Upstream dependencies | forge-console-api |
| Downstream consumers | all tenant-scoped services |
| Security boundary | tenant boundary; no cross-tenant reads |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `foundation` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

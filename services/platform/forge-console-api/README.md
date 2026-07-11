# forge-console-api

| Field | Value |
|---|---|
| Service name | `forge-console-api` |
| Bounded context | B-department operator API/UI backend |
| Primary responsibility | B부서 UI, RBAC, run 생성·승인 |
| Owned data | run metadata |
| Consumed contracts | operator commands; approval actions |
| Published events | run.created.v1 (PROPOSED); approval events |
| Consumed events | plan.contract.*; quality.gate.*; handoff-ready signals |
| Upstream dependencies | operator-console (apps) |
| Downstream consumers | tenant-control-service; repository-intake-service; plan-contract-service |
| Security boundary | RBAC; no production deploy credentials |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

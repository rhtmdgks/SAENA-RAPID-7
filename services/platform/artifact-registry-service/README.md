# artifact-registry-service

| Field | Value |
|---|---|
| Service name | `artifact-registry-service` |
| Bounded context | Run artifact storage |
| Primary responsibility | patch, PR bundle, screenshots, raw responses, reports |
| Owned data | object manifest |
| Consumed contracts | artifact uploads; content hashes |
| Published events | artifact.registered.v1 (PROPOSED) |
| Consumed events | patch.unit.completed.v1; observation.captured.v1; quality.gate.* |
| Upstream dependencies | agent-runner-service; chatgpt-observer-service; quality-eval-service |
| Downstream consumers | forge-console-api; audit-ledger-service |
| Security boundary | tenant-scoped object storage; content-hash addressing |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

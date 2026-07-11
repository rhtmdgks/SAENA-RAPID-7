# policy-gate-service

| Field | Value |
|---|---|
| Service name | `policy-gate-service` |
| Bounded context | Authorization / policy-as-code |
| Primary responsibility | OPA-style policy; command/file/network/tool authorization |
| Owned data | signed policy decisions |
| Consumed contracts | Action Contract; tool/file/network requests |
| Published events | policy.decision.recorded.v1 (PROPOSED) |
| Consumed events | plan.contract.approved.v1 |
| Upstream dependencies | agent-orchestrator-service; agent-runner-service |
| Downstream consumers | agent-runner-service; audit-ledger-service |
| Security boundary | default-deny; least privilege |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `foundation` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

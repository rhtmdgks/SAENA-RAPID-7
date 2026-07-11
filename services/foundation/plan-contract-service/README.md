# plan-contract-service

| Field | Value |
|---|---|
| Service name | `plan-contract-service` |
| Bounded context | Action Contract lifecycle |
| Primary responsibility | Plan Mode results → Action Contract structure/validation; propose→approve state |
| Owned data | action contracts |
| Consumed contracts | plan drafts; evidence IDs; patch unit candidates |
| Published events | plan.contract.proposed.v1; plan.contract.approved.v1 |
| Consumed events | intervention candidates; discovery/demand/claim artifacts (PROPOSED) |
| Upstream dependencies | intervention-generator-service; forge-console-api |
| Downstream consumers | agent-orchestrator-service; policy-gate-service |
| Security boundary | human-approval-gated; signed contract immutability |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `foundation` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

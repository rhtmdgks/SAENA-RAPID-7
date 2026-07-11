# agent-orchestrator-service

| Field | Value |
|---|---|
| Service name | `agent-orchestrator-service` |
| Bounded context | MAS / Temporal orchestration |
| Primary responsibility | MAS DAG, state machine, retry, approval pause |
| Owned data | workflow state |
| Consumed contracts | signed Action Contracts |
| Published events | workflow.state.changed.v1 (PROPOSED) |
| Consumed events | plan.contract.approved.v1; quality.gate.* |
| Upstream dependencies | plan-contract-service; forge-console-api |
| Downstream consumers | agent-runner-service; policy-gate-service; quality-eval-service |
| Security boundary | WAITING_APPROVAL→EXECUTING only via signed approval |
| Planned runtime | k3s Deployment + Temporal (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

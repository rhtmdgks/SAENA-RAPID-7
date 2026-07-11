# agent-runner-service

| Field | Value |
|---|---|
| Service name | `agent-runner-service` |
| Bounded context | Isolated agent execution |
| Primary responsibility | 격리 worktree/container에서 Codex/Claude/Cursor adapter 실행 |
| Owned data | ephemeral run artifacts |
| Consumed contracts | Action Contract; policy lease |
| Published events | patch.unit.completed.v1 |
| Consumed events | plan.contract.approved.v1; workflow execution signals |
| Upstream dependencies | agent-orchestrator-service; policy-gate-service |
| Downstream consumers | quality-eval-service; artifact-registry-service; audit-ledger-service |
| Security boundary | ephemeral Jobs; NetworkPolicy default-deny; short-lived tokens |
| Planned runtime | Kubernetes Job (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

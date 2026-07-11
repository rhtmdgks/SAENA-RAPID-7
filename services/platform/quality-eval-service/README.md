# quality-eval-service

| Field | Value |
|---|---|
| Service name | `quality-eval-service` |
| Bounded context | Deterministic quality gates |
| Primary responsibility | build, test, lint, schema, link, a11y, content-evidence, diff eval |
| Owned data | test/eval evidence |
| Consumed contracts | patch units; quality-gates.yaml |
| Published events | quality.gate.passed.v1; quality.gate.failed.v1 |
| Consumed events | patch.unit.completed.v1 |
| Upstream dependencies | agent-runner-service |
| Downstream consumers | artifact-registry-service; agent-orchestrator-service; audit-ledger-service |
| Security boundary | critical gates skip 금지; independent of author agent self-eval |
| Planned runtime | k3s Deployment + Jobs (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

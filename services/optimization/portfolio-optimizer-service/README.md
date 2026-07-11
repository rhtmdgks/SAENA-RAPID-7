# portfolio-optimizer-service

| Field | Value |
|---|---|
| Service name | `portfolio-optimizer-service` |
| Bounded context | Constrained intervention portfolio selection |
| Primary responsibility | constrained Bayesian optimization/bandit action selection |
| Owned data | portfolio decisions |
| Consumed contracts | predictions; cost/risk/capacity constraints |
| Published events | portfolio.selected.v1 (PROPOSED) |
| Consumed events | prediction.scored.v1; intervention.candidates.ready.v1 |
| Upstream dependencies | digital-twin-service; intervention-generator-service |
| Downstream consumers | plan-contract-service |
| Security boundary | P1/P2; KPI weight auto-opt OFF in P0 |
| Planned runtime | k3s Deployment; featureFlags.portfolioOptimizer |
| Domain area | `optimization` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

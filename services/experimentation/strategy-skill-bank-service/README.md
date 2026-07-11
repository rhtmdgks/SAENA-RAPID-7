# strategy-skill-bank-service

| Field | Value |
|---|---|
| Service name | `strategy-skill-bank-service` |
| Bounded context | Privacy-preserving strategy transfer |
| Primary responsibility | versioned positive/negative strategy cards; privacy filter |
| Owned data | skill cards |
| Consumed contracts | verified experiment outcomes |
| Published events | strategy.card.eligible.v1 |
| Consumed events | experiment.outcome.observed.v1 |
| Upstream dependencies | experiment-attribution-service |
| Downstream consumers | intervention-generator-service; planner artifacts |
| Security boundary | aggregate_only; no proprietary customer content sharing |
| Planned runtime | k3s Deployment; featureFlags.strategySkillBank |
| Domain area | `experimentation` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

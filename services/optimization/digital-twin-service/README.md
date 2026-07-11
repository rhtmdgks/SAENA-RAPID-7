# digital-twin-service

| Field | Value |
|---|---|
| Service name | `digital-twin-service` |
| Bounded context | Time-to-signal predictive model |
| Primary responsibility | time-to-signal, citation, absorption 확률·uncertainty 모델 |
| Owned data | model features/predictions |
| Consumed contracts | historical outcomes; site features |
| Published events | prediction.scored.v1 (PROPOSED) |
| Consumed events | experiment.outcome.observed.v1; intervention.candidates.ready.v1 |
| Upstream dependencies | experiment-attribution-service; intervention-generator-service |
| Downstream consumers | portfolio-optimizer-service |
| Security boundary | P1; aggregate learning only; no customer proprietary text in shared models |
| Planned runtime | k3s Deployment; featureFlags.digitalTwin |
| Domain area | `optimization` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

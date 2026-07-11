# experiment-attribution-service

| Field | Value |
|---|---|
| Service name | `experiment-attribution-service` |
| Bounded context | Causal experiment measurement |
| Primary responsibility | treatment/control, DiD, sequential evidence, long-term attribution |
| Owned data | experiment results |
| Consumed contracts | observation cells; treatment/control defs |
| Published events | experiment.outcome.observed.v1 |
| Consumed events | observation.captured.v1; citation.normalized.v1; patch.unit.completed.v1 |
| Upstream dependencies | chatgpt-observer-service; citation-intelligence-service; agent-runner-service (patch.unit.completed.v1 소비와 정합화 — 2026-07-12 감사) |
| Downstream consumers | strategy-skill-bank-service; digital-twin-service; forge-console-api |
| Security boundary | no lift claim without registered evidence; conversion attribution not 7-day success |
| Planned runtime | k3s Deployment; featureFlags.experimentAttribution |
| Domain area | `experimentation` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

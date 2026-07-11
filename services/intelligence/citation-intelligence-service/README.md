# citation-intelligence-service

| Field | Value |
|---|---|
| Service name | `citation-intelligence-service` |
| Bounded context | Citation selection intelligence |
| Primary responsibility | citation URL normalization, source ownership, contribution scoring |
| Owned data | citation records |
| Consumed contracts | observation snapshots |
| Published events | citation.normalized.v1 |
| Consumed events | observation.captured.v1 |
| Upstream dependencies | chatgpt-observer-service |
| Downstream consumers | absorption-analysis-service; experiment-attribution-service |
| Security boundary | raw snapshots as object refs; tenant-scoped |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `intelligence` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

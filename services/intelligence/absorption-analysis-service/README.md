# absorption-analysis-service

| Field | Value |
|---|---|
| Service name | `absorption-analysis-service` |
| Bounded context | Answer absorption analysis |
| Primary responsibility | answer slot alignment, claim overlap, prominence/narrative consistency |
| Owned data | absorption labels |
| Consumed contracts | citations; claims; observation text |
| Published events | absorption.analyzed.v1 (PROPOSED) |
| Consumed events | citation.normalized.v1 |
| Upstream dependencies | citation-intelligence-service; claim-evidence-service |
| Downstream consumers | digital-twin-service; experiment-attribution-service |
| Security boundary | P1 feature flag; decision output gated until data ready |
| Planned runtime | k3s Deployment (CONFIRMED intent); featureFlags.absorptionAnalysis |
| Domain area | `intelligence` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

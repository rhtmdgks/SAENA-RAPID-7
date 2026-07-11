# engine-adapter-gateway

| Field | Value |
|---|---|
| Service name | `engine-adapter-gateway` |
| Bounded context | Provider/engine adapter boundary |
| Primary responsibility | provider adapter contract, feature flags, rate limits |
| Owned data | adapter config |
| Consumed contracts | engine-scoped observation/optimization requests |
| Published events | adapter.config.updated.v1 (PROPOSED) |
| Consumed events | — |
| Upstream dependencies | chatgpt-observer-service; future adapters |
| Downstream consumers | packages/provider-adapters/* |
| Security boundary | v1: chatgpt-search ON; google/gemini feature flag OFF / scale 0 |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

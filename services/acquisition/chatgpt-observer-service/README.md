# chatgpt-observer-service

| Field | Value |
|---|---|
| Service name | `chatgpt-observer-service` |
| Bounded context | ChatGPT Search observation |
| Primary responsibility | approved ChatGPT Search observation; raw snapshot capture |
| Owned data | observation ledger (ROL) — **계약은 엔진 중립 `PlatformObservation`(+engine_id), 본 서비스는 그 첫 구현체 (ADR-0007). 2번째 엔진 = 동일 계약의 신규 observer, core 재작업 0** |
| Consumed contracts | observation cells; locale/browser policy |
| Published events | observation.captured.v1 |
| Consumed events | plan.contract.approved.v1 (measurement phase); baseline registration (PROPOSED) |
| Upstream dependencies | engine-adapter-gateway; forge-console-api |
| Downstream consumers | citation-intelligence-service; experiment-attribution-service |
| Security boundary | rate-limited; ToS-compliant; approved observation only |
| Planned runtime | k3s Deployment + browser Jobs (CONFIRMED intent) |
| Domain area | `acquisition` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

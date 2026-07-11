# observability-service

| Field | Value |
|---|---|
| Service name | `observability-service` |
| Bounded context | Platform observability |
| Primary responsibility | OpenTelemetry traces, metrics, SLO, cost and drift alarms |
| Owned data | telemetry |
| Consumed contracts | OTel signals from all services |
| Published events | slo.alert.fired.v1 (PROPOSED) |
| Consumed events | — (pull/metrics; OPEN DECISION for alert events) |
| Upstream dependencies | all services |
| Downstream consumers | operators; SRE runbooks |
| Security boundary | no secrets in traces; tenant labels required |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `platform` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

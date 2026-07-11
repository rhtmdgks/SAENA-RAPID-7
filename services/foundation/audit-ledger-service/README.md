# audit-ledger-service

| Field | Value |
|---|---|
| Service name | `audit-ledger-service` |
| Bounded context | Immutable audit trail |
| Primary responsibility | append-only run/event/hash chain; evidence bundle integrity |
| Owned data | audit log |
| Consumed contracts | run events; approval events; quality results |
| Published events | audit.event.appended.v1 (PROPOSED) |
| Consumed events | plan.contract.*; patch.unit.*; quality.gate.*; experiment.outcome.* |
| Upstream dependencies | all planes |
| Downstream consumers | forge-console-api; compliance consumers |
| Security boundary | append-only; immutable role access |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `foundation` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

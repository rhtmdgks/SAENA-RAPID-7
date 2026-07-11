# repository-intake-service

| Field | Value |
|---|---|
| Service name | `repository-intake-service` |
| Bounded context | Customer source intake |
| Primary responsibility | Git/zip intake, commit pinning, SBOM·secret scan |
| Owned data | repository manifest |
| Consumed contracts | intake requests; read-only source credentials (leased) |
| Published events | repo.intaken.v1 |
| Consumed events | — |
| Upstream dependencies | forge-console-api |
| Downstream consumers | site-discovery-service; agent-runner-service |
| Security boundary | tenant-scoped secrets; secret scan before agent context |
| Planned runtime | k3s Deployment + Jobs (CONFIRMED intent) |
| Domain area | `acquisition` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

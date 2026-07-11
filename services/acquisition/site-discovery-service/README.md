# site-discovery-service

| Field | Value |
|---|---|
| Service name | `site-discovery-service` |
| Bounded context | Technical site inventory |
| Primary responsibility | route, framework, render, robots, canonical, sitemap audit |
| Owned data | site inventory |
| Consumed contracts | repository manifest; site URLs |
| Published events | site.inventory.completed.v1 |
| Consumed events | repo.intaken.v1 |
| Upstream dependencies | repository-intake-service |
| Downstream consumers | demand-graph-service; intervention-generator-service |
| Security boundary | read-only discovery; untrusted web content quarantine |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `acquisition` |
| Implementation status | **NOT IMPLEMENTED** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4

## Status

NOT IMPLEMENTED — Bootstrap scaffolding only. No source, Dockerfile, or package manifest.

# profile:development

## Purpose

Local/k3d development. Customer source forbidden.

## Scope

Values overlays / adapter config only — no algorithm forks.

## Current decision

PROPOSED profile folder. Principles CONFIRMED in deployment-profiles.md.

This directory will hold the **development values overlay** for the
`saena-forge` Helm chart — i.e. the k3d-dev-facing Helm values (image tags,
resource requests sized for a single-node laptop cluster, engine flags,
adapter endpoints pointing at `tools/development/docker-compose.dev.yaml`
services). The chart itself (`deploy/charts/`) lands in W2C; this overlay
cannot be populated before the chart exists, so no `values.yaml` is created
in this patch unit (T15).

Mapping to the local dev substrate (`docs/architecture/dev-environment.md`,
ADR-0022 Tier2):

| Layer | Location | Status |
|---|---|---|
| Workload cluster | `tools/development/k3d-dev.yaml` (k3d single-node) | T15 |
| Stateful deps (outside k3d) | `tools/development/docker-compose.dev.yaml` | T15 (postgres only; temporal-dev/redpanda placeholders) |
| Chart | `deploy/charts/` | PLANNED — W2C |
| This overlay (`values.yaml`) | `deploy/profiles/development/` | PLANNED — depends on chart landing first |

Constraints inherited from k3s spec §5.1 Developer profile: single node,
no customer source (synthetic tenants/fixtures only), minimal footprint —
this overlay must not diverge from those constraints once populated.

## Constraints

- Fixed or per-tenant tenant_id still required in contracts
- Engine flags: ChatGPT on; Google/Gemini off in v1
- No customer source — synthetic tenants only (k3s spec §5.1)

## Open decisions

- Concrete values files — NOT IMPLEMENTED, blocked on `deploy/charts/` (W2C)

## Source specification references

- docs/architecture/deployment-profiles.md
- docs/architecture/dev-environment.md
- docs/decisions/ADR-0022-dev-environment.md
- docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md §5.1

## Status

PLANNED — no chart values yet (blocked on `deploy/charts/`, W2C)

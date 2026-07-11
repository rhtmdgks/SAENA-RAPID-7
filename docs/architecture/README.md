# Architecture docs

## Purpose

Living architecture index for SAENA RAPID-7 + FORGE. Specs under `docs/specs/` are authoritative originals.

## Scope

Service catalog, contracts, tenancy, security, observability, testing, deployment profiles, worktree ownership.

## Current decision

PROPOSED documentation set reflecting CONFIRMED items from v1 specs; no silent new tech choices.

## Documents

| Doc | Topic |
|---|---|
| system-context.md | System context & planes |
| service-catalog.md | 24 services + domain mapping |
| dependency-policy.md | Allowed dependency directions |
| data-ownership.md | Per-service data ownership |
| api-event-contracts.md | API/event contract principles |
| tenancy-model.md | Tenant identifiers & isolation |
| security-model.md | Security boundaries |
| observability.md | OTel / SLO / audit |
| testing-strategy.md | Test layers |
| deployment-profiles.md | development / internal-k3s / saas-* |
| worktree-ownership.md | Agent worktree exclusivity |

## Constraints

- Do not modify `docs/specs/*_v1.md`
- Mark CONFIRMED / PROPOSED / OPEN DECISION / NOT IMPLEMENTED / OUT OF SCOPE

## Open decisions

See individual docs and design §13 / k3s §12.

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md`
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md`
- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md`

## Status

PROPOSED index / NOT IMPLEMENTED runtime

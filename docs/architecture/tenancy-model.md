# Tenancy model

## Purpose

Tenant-aware design for internal-k3s and future SaaS profiles.

## Scope

Identifiers, isolation, namespaces, source isolation.

## Current decision

**CONFIRMED**

- Every customer run: independent namespace, short-lived workspace, tenant-scoped secret
- Events/records carry `tenant_id` (and related IDs as applicable)
- Customer source processed only in per-run isolated workspace
- Central API does not directly edit customer code

**PROPOSED** for SaaS reuse

- Same SAENA Core container images across profiles
- Profile-specific config + infrastructure adapters only
- `internal-k3s` uses a fixed `tenant_id` (single-operator context) but still threads IDs
- SaaS: per-tenant isolation of data, cache, events, workflow namespaces

## Identifier set (required future acceptance)

| ID | Role |
|---|---|
| tenant_id | hard isolation boundary |
| workspace_id | operator/customer workspace |
| project_id | engagement/project |
| site_id | domain/site under project |
| run_id | single FORGE run |
| actor_id | human or system actor |

## Constraints

- Cross-tenant access target: 0
- Strategy Skill Bank: aggregate_only; no proprietary customer text sharing
- Redis not a cross-tenant source of truth

## Open decisions

- SaaS auth/billing — OUT OF SCOPE for this bootstrap (explicitly not implemented)
- Namespace naming `saena-tenant-<id>` finalization — CONFIRMED intent in k3s spec

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.1
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §1, §5–6

## Status

CONFIRMED isolation principles / NOT IMPLEMENTED enforcement

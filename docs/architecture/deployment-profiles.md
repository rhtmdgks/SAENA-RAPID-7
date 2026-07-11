# Deployment profiles

## Purpose

Separate deployment profiles without leaking into algorithm code.

## Scope

Four bootstrap profiles + relation to k3s operational profiles.

## Current decision

**CONFIRMED principles**

- Same SAENA Core container images across profiles
- Environment configuration + infrastructure adapters separated
- `internal-k3s` still uses `tenant_id` (fixed/single-operator) threaded through contracts
- SaaS: per-tenant data/cache/event/workflow namespace isolation
- Customer source only in per-execution isolated workspace
- Central API server does not directly modify customer code
- Deployment profile must not penetrate algorithm code

**PROPOSED profile folder set** (this repo)

| Profile | Path | Intent |
|---|---|---|
| development | `deploy/profiles/development/` | local/k3d skill-eval; customer source forbidden |
| internal-k3s | `deploy/profiles/internal-k3s/` | B부서 production-shaped package |
| saas-shared | `deploy/profiles/saas-shared/` | future multi-tenant shared SaaS |
| saas-dedicated | `deploy/profiles/saas-dedicated/` | future dedicated SaaS |

k3s spec also describes Developer / Internal Staging / Internal Production / Air-gap operational profiles — map onto the above via values overlays (**PROPOSED** mapping).

## Constraints

- Helm values reference secrets; never embed secret material
- v1 engine flags: chatgptSearch true; google/gemini false
- Agent runners: Jobs with TTL destroy
- OUT OF SCOPE now: real SaaS auth/billing/metering code

## Open decisions

- Air-gap as subset of internal-k3s vs separate profile folder — OPEN DECISION
- SaaS tenancy billing model — OUT OF SCOPE / OPEN DECISION

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §5, §7
- User bootstrap requirements §6

## Status

CONFIRMED principles / PROPOSED folder names / NOT IMPLEMENTED charts

# Dependency policy

## Purpose

Allowed dependency directions between packages, services, and planes.

## Scope

Code dependencies (future) and runtime call/event directions.

## Current decision

**PROPOSED** policy derived from CONFIRMED contract-first / no shared DB rules.

## Allowed directions (PROPOSED)

```text
apps → services (via contracts) → packages/{contracts,schemas,domain,shared}
services ✗→ other services' databases
services → events (publish/consume versioned)
packages/provider-adapters → packages/contracts (interfaces only)
algorithm/domain ✗→ deploy profile packages
deploy ✗→ algorithm source
```

## Rules

1. Depend on contracts/schemas, not concrete service internals.
2. State changes via versioned events; sync limited to query/command APIs.
3. Provider-specific code only under `packages/provider-adapters/<provider>/`.
4. Infrastructure adapters (storage, queue, k8s) isolated from AEO scoring logic.
5. No dependency install by agents without pin + allowlist (runtime policy).

## Constraints

- Bootstrap: no package manager lockfiles / manifests yet (OPEN DECISION language stack)

## Open decisions

- Primary languages per service — OPEN DECISION
- Monorepo tooling (Nx/Bazel/etc.) — OPEN DECISION

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §4.1
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.1

## Status

PROPOSED

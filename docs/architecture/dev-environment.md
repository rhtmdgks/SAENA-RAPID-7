# Dev environment

## Purpose

Define the 2-tier local development profile (ADR-0022) so every session runs
against a reproducible, cluster-optional local substrate — reproducibility is
the precondition for evidence-based verification (CLAUDE.md 원칙 11).

## Scope

In: Tier1 (no-cluster) and Tier2 (k3d dev) local execution modes, the
`tools/development/*` artifacts that implement Tier2, worktree conventions
cross-link, customer-source prohibition, Apple Silicon docker-in-docker
fallback.
Out: devcontainer image contents (ADR-0022 devcontainer section, T14),
runner ephemeral workspace (W3), Helm chart contents (`deploy/` — W2C).

## Current decision

**CONFIRMED** tier definitions from ADR-0022. This document elaborates the
operational detail; the ADR remains the decision record.

### Tier1 — no-cluster

- Scope: W0–W1 default. Contract/schema work, unit tests, boundary checks.
- No cluster, no compose stack required.
- Commands:
  - `uv sync --locked` — install pinned dependencies (`just setup`).
  - `uv run just verify` — local gate mirror of CI (lint, typecheck, test,
    boundaries, contracts-validate).
  - `uv run just contracts-validate` — validate `packages/contracts/**`
    schemas in isolation when a full `verify` run isn't needed.
- If a task doesn't need a running service or database, stay in Tier1 — do
  not stand up Tier2 infrastructure for contract/unit-test work.

### Tier2 — k3d dev

- Scope: defined in W0 (this document + the two config files below), first
  real use from W2A (service integration execution).
- Composition:
  - `tools/development/docker-compose.dev.yaml` — stateful Tier-2
    dependencies that run OUTSIDE k3d (postgres now; temporal-dev/redpanda
    reserved as commented placeholders for W2B/W2C).
  - `tools/development/k3d-dev.yaml` — single-node k3d cluster
    (`saena-dev`) that hosts the actual service/workload containers. It does
    not declare stateful dependencies; those stay in compose.
- Why split: k3d workload restarts (image rebuilds, pod evictions) are
  frequent during iteration; keeping stateful services in a separately
  managed compose stack avoids losing dev data on every cluster recreate and
  keeps the k3d config minimal.
- Subset execution rule (`uv run just dev-up <service...>`): only start the
  target service plus its direct synchronous dependencies — do not bring up
  the full stack for a single-service task. This mirrors the synchronous-call
  discipline in `docs/architecture/dependency-policy.md` rule 6 (the three
  allowed synchronous call kinds), scoped down to the local dev-up target: a
  service's local dependency set should stay small (bounded, low single
  digits) because rule 6 caps the callable dependency shapes a service can
  have in the first place. If a task genuinely needs more than that, treat
  it as a signal to re-check the service's dependency direction against
  `dependency-policy.md` before just widening `dev-up`.
- Values overlay for the workloads themselves lives under
  `deploy/profiles/development/` (Helm chart values — chart lands W2C, see
  that directory's README for current status).
- Round-trip lifecycle for local validation only:
  `k3d cluster create --config tools/development/k3d-dev.yaml` →
  `kubectl get nodes` → `k3d cluster delete saena-dev`. This is a disposable
  local check, not a deployment (CLAUDE.md 원칙 10 is about production
  deploy/push/merge and does not apply to local throwaway clusters).

## Worktree conventions

Local dev environment work happens inside per-unit worktrees per ADR-0023
(`docs/decisions/ADR-0023-worktree-execution-conventions.md`): sibling
directory `../SAENA-RAPID-7.worktrees/<unit-id>/`, branch
`unit/<unit-id>`, lifecycle managed by `tools/development/worktree.sh`
(`just worktree-create` / `just worktree-destroy` / `just worktree-audit`).
Tier2 compose/k3d state is local-machine scoped and is not part of worktree
ownership — multiple worktrees on the same machine share one Tier2 stack
unless explicitly namespaced per-unit.

## Customer-source prohibition

Neither tier may use real customer source or customer data. Tier2 follows
k3s spec §5.1 Developer profile constraints: single node, synthetic tenants
only, no customer source. Fixtures used against Tier2 postgres (or later
temporal-dev/redpanda) must be synthetic.

## Apple Silicon docker-in-docker note

docker-in-docker (used by the devcontainer's k3d feature, ADR-0022) has
known instability on Apple Silicon hosts. Fallback: run k3d directly on the
host (outside any container) instead of nesting it inside the devcontainer.
`tools/development/k3d-dev.yaml` works identically either way — point a
host-installed `k3d`/`docker` at the same config file. `.tool-versions`
(mise) is the non-container path that keeps tool versions aligned with the
devcontainer pins when running host-side.

## Constraints

- Customer source forbidden in both tiers (k3s spec §5.1).
- Tier2 compose services are local-only — never used in production; `deploy/`
  charts remain the deployment SSOT (`docs/architecture/deployment-profiles.md`).
- k3d cluster create/delete round-trips are local verification only, not a
  deployment path.

## Open decisions

- Per-unit Tier2 namespacing (shared vs isolated compose/k3d stacks across
  concurrent worktrees) — OPEN DECISION, revisit if concurrent Tier2 usage
  becomes common before W2A.
- Temporal-dev and redpanda concrete image tags/healthchecks — owned by
  W2B/W2C respectively (placeholders only in this patch unit).

## Source specification references

- `docs/decisions/ADR-0022-dev-environment.md`
- `docs/decisions/ADR-0023-worktree-execution-conventions.md`
- `docs/architecture/deployment-profiles.md`
- `docs/architecture/dependency-policy.md` (rule 6)
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §5.1

## Status

CONFIRMED tier principles (ADR-0022) / IMPLEMENTED Tier2 config artifacts
(this patch unit, T15) / NOT IMPLEMENTED Tier2 chart values (W2C)

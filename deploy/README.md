# deploy/

## Purpose

Helm charts, profiles, policies, environments. Protected path.

## Scope

charts/, profiles/, policies/, environments/.

## Current decision

CONFIRMED Helm/OCI packaging intent; chart contents NOT IMPLEMENTED (no deployable chart).

**CONFIRMED (2026-07-12, user decision):** official Helm chart name is `saena-forge`. Not used: `forge` (collision-prone), `saena-forge-chart` (redundant suffix). Specs use both older forms; this decision supersedes them for implementation. No Chart.yaml/Helm resources created yet.

## Constraints

- Agents: no kubectl apply / helm upgrade
- Values reference secrets only

## Open decisions

- (chart identity — RESOLVED, see Current decision above)

## Source specification references

- k3s §2, §7–8

## Status

NOT IMPLEMENTED (skeleton)

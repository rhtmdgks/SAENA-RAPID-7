# Runbooks

## Purpose

Operational runbooks for install, upgrade, rollback, incidents.

## Scope

Skeleton only. Detailed procedures in k3s spec §8 — to be copied/adapted later.

## Current decision

PROPOSED runbook set:

- [ ] preflight
- [ ] install/upgrade
- [ ] smoke tests
- [ ] rollback (chart/policy/skill/runner/migration/customer patch)
- [ ] suspend runners / revoke credentials

## Constraints

- `--atomic` Helm does not fully roll back data — expand/contract migrations
- Agents must not `kubectl apply` / deploy

## Open decisions

- `forgectl` CLI delivery — NOT IMPLEMENTED

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §8

## Status

NOT IMPLEMENTED

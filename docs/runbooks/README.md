# Runbooks

## Purpose

Operational runbooks for install, upgrade, rollback, incidents.

## Scope

k3s operational runbooks are skeleton only (detailed procedures in k3s spec §8
— to be copied/adapted later). The **Wave 6 operator runbook** below is
IMPLEMENTED and tested.

## Runbooks

- [`wave6-operator-runbook.md`](wave6-operator-runbook.md) — **IMPLEMENTED**
  (2026-07-19). New-computer setup, `scripts/bootstrap-claude.sh`, skill-pack
  plugin install/update/uninstall, starting Claude Code from RAPID-7, and
  driving `saena-pilot` against an external customer repo (7 modes, evidence,
  rollback, troubleshooting). Every command block verified by real execution.

## Current decision

PROPOSED k3s runbook set:

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

Wave 6 operator runbook IMPLEMENTED (2026-07-19); k3s runbooks NOT IMPLEMENTED

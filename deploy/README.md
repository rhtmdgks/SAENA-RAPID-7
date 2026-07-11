# deploy/

## Purpose

Helm charts, profiles, policies, environments. Protected path.

## Scope

charts/, profiles/, policies/, environments/.

## Current decision

CONFIRMED Helm/OCI packaging intent; chart contents NOT IMPLEMENTED (no deployable chart).

## Constraints

- Agents: no kubectl apply / helm upgrade\n- Values reference secrets only

## Open decisions

- Chart name saena-forge vs forge — spec uses both forms; OPEN DECISION on final chart identity string

## Source specification references

- k3s §2, §7–8

## Status

NOT IMPLEMENTED (skeleton)

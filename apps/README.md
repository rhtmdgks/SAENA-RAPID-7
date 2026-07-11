# apps/

## Purpose

User-facing and edge applications.

## Scope

operator-console, api-gateway skeletons.

## Current decision

PROPOSED app split. forge-console-api remains a service.

## Constraints

- No production deploy credentials
- ChatGPT Search only messaging in UI copy (future)

## Open decisions

- Whether api-gateway owns BFF vs forge-console-api — OPEN DECISION

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §7
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3.1

## Status

NOT IMPLEMENTED

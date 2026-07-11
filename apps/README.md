# apps/

## Purpose

User-facing and edge applications.

## Scope

operator-console, api-gateway skeletons.

## Current decision

operator-console = v1 UI (CONFIRMED need). api-gateway = **FUTURE (SaaS)** — v1 edge는 forge-console-api 단독 (ADR-0007, 2026-07-12).

## Constraints

- No production deploy credentials
- ChatGPT Search only messaging in UI copy (future)

## Open decisions

- ~~Whether api-gateway owns BFF vs forge-console-api~~ — RESOLVED (ADR-0007)

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §7
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3.1

## Status

NOT IMPLEMENTED

# profile:saas-shared

## Purpose

Future shared multi-tenant SaaS. Same core images; isolated namespaces.

## Scope

Values overlays / adapter config only — no algorithm forks.

## Current decision

PROPOSED profile folder. Principles CONFIRMED in deployment-profiles.md.

## Constraints

- Fixed or per-tenant tenant_id still required in contracts
- Engine flags: ChatGPT on; Google/Gemini off in v1

## Open decisions

- Concrete values files — NOT IMPLEMENTED

## Source specification references

- docs/architecture/deployment-profiles.md

## Status

NOT IMPLEMENTED

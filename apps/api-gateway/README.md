# api-gateway

## Purpose

PROPOSED edge gateway for console/external exposure.

## Scope

Routing, authn termination (future), rate limits.

## Current decision

**FUTURE (SaaS) — v1 범위 제외 (ADR-0007, 2026-07-12).** v1 edge = forge-console-api 단독 (internal k3s, B부서 전용). North-south gateway는 SaaS 외부 노출 시점에 재도입. 폴더는 재도입 경로로 보존.

## Constraints

- Least privilege
- No customer source mutation

## Open decisions

- ~~Merge with forge-console-api vs separate~~ — RESOLVED (ADR-0007): v1은 forge-console-api 단독, 본 gateway는 SaaS 시점 재검토

## Source specification references

- k3s §1 Internal API notes

## Status

FUTURE (SaaS) / NOT IMPLEMENTED

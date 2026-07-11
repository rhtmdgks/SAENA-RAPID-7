# packages/

## Purpose

Shared libraries and contracts. No service business DBs here.

## Scope

contracts, schemas, domain, provider-adapters, source-connectors, observability, security, testing, shared.

## Current decision

PROPOSED package set for monorepo reuse.

## Constraints

- Algorithm must not depend on deploy profiles
- Provider isolation mandatory

## Open decisions

- ~~Language/package manager~~ — **확정 (ADR-0009/0010)**: Python 3.12 + uv workspaces. 수기 계약 SSOT = `packages/contracts`, 파생 산출 = `packages/schemas` (ADR-0011)

## Source specification references

- k3s §2 contracts/; Algorithm §8 adapter layers

## Status

NOT IMPLEMENTED

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

- Language/package manager — OPEN DECISION

## Source specification references

- k3s §2 contracts/; Algorithm §8 adapter layers

## Status

NOT IMPLEMENTED

# Data ownership

## Purpose

Per-service owned data and store classes.

## Scope

Logical ownership only. Physical schemas NOT IMPLEMENTED.

## Current decision

**CONFIRMED** ownership column from Algorithm §6.2.  
**CONFIRMED** store classes from Algorithm §6.4 (Postgres, ClickHouse, object storage, vector, graph P1, Redis ephemeral).

## Ownership table

See `service-catalog.md` and each `services/**/README.md` "Owned data" field.

## Store classes (CONFIRMED intent)

| Store | Use | Principle |
|---|---|---|
| PostgreSQL | tenancy, workflow, Action Contract, policy, metadata | strong transactions |
| ClickHouse | event/observation/metrics analytics | append-only |
| Object storage | raw responses, snapshots, artifacts, SBOM | content hash + lifecycle |
| Qdrant/pgvector | retrieval | tenant partition |
| Graph store | QEEG/TAG | P1 |
| Redis | locks, rate limits, short-lived state | not system of record |

## Constraints

- Own DB or own schema per service
- No PII/secrets in event payloads — object refs + access policy
- Tenant identifiers on core records (see tenancy-model.md)

## Open decisions

- Graph store product choice — OPEN DECISION
- Managed vs in-cluster data services per profile — see deployment-profiles.md

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2, §6.4
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §4

## Status

CONFIRMED ownership intent / NOT IMPLEMENTED schemas

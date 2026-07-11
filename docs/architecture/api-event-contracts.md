# API and event contracts

## Purpose

Contract-first and event-contract-first rules before any implementation.

## Scope

gRPC/Protobuf internal APIs; versioned events; JSON Schema Action Contract.

## Current decision

**CONFIRMED**

- Internal API: gRPC + Protobuf
- External console API: REST/GraphQL as required
- Events: versioned topics; at-least-once; idempotent consumers
- Action Contract: JSON Schema validated; human approval required

## Required event envelope fields (CONFIRMED)

`event_id`, `tenant_id`, `run_id`, `schema_version`, `producer`, `occurred_at`, `trace_id`, `idempotency_key`

## Recommended topics (CONFIRMED list from design)

- `repo.intaken.v1`
- `site.inventory.completed.v1`
- `demand.graph.versioned.v1`
- `observation.captured.v1`
- `citation.normalized.v1`
- `plan.contract.proposed.v1`
- `plan.contract.approved.v1`
- `patch.unit.completed.v1`
- `quality.gate.passed|failed.v1`
- `experiment.outcome.observed.v1`
- `strategy.card.eligible.v1`

Additional topics in service READMEs marked **PROPOSED**.

## Core business identifiers (document now; schemas later)

All core data contracts MUST be able to carry:

- `tenant_id`
- `workspace_id`
- `project_id`
- `site_id`
- `run_id`
- `actor_id`

## Provider interface candidates (PROPOSED names; no code yet)

- `CrawlerPolicy`
- `RetrievalEligibility`
- `QueryGenerator`
- `ProbeRunner`
- `CitationExtractor`
- `VisibilityScorer`
- `TelemetryConnector`
- `OptimizationPolicy`

## Constraints

- No silent breaking changes; compatibility tests under `packages/contracts` / `events`
- Single owner for contracts/schemas/events/migrations

## Open decisions

- Exact protobuf package naming — OPEN DECISION
- AsyncAPI vs protobuf-only for events — OPEN DECISION (k3s repo sketch includes asyncapi/)

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §1, §4
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5.2, §6.3

## Status

CONFIRMED principles / NOT IMPLEMENTED schemas

# Event catalog

## Purpose

Human-readable catalog of versioned events.

## Scope

Bootstrap lists recommended + proposed topics.

## Current decision

### CONFIRMED (design recommended)

| Topic | Producer (typical) |
|---|---|
| repo.intaken.v1 | repository-intake-service |
| site.inventory.completed.v1 | site-discovery-service |
| demand.graph.versioned.v1 | demand-graph-service |
| observation.captured.v1 | chatgpt-observer-service |
| citation.normalized.v1 | citation-intelligence-service |
| plan.contract.proposed.v1 | plan-contract-service |
| plan.contract.approved.v1 | plan-contract-service |
| patch.unit.completed.v1 | agent-runner-service |
| quality.gate.passed.v1 / failed.v1 | quality-eval-service |
| experiment.outcome.observed.v1 | experiment-attribution-service |
| strategy.card.eligible.v1 | strategy-skill-bank-service |

### PROPOSED (service READMEs; not yet in design topic list)

tenant.policy.updated.v1, audit.event.appended.v1, entity.graph.versioned.v1, claim.evidence.versioned.v1, absorption.analyzed.v1, intervention.candidates.ready.v1, prediction.scored.v1, portfolio.selected.v1, workflow.state.changed.v1, artifact.registered.v1, adapter.config.updated.v1, slo.alert.fired.v1, run.created.v1

## Constraints

Schema files go under `events/schemas/` (future).

## Open decisions

- Finalize PROPOSED topics via ADR before implementation

## Source specification references

- Algorithm §6.3

## Status

CONFIRMED core list / PROPOSED extensions / NOT IMPLEMENTED schemas

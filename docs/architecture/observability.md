# Observability

## Purpose

Observable-by-default requirements.

## Scope

Traces, metrics, logs, audit envelope, dashboards, retention.

## Current decision

**CONFIRMED** intent: OpenTelemetry; required dashboards; run trace envelope fields in k3s §9.

## Run trace envelope (CONFIRMED fields)

`trace_id`, `run_id`, `tenant_id`, `repo_sha`, `chart_version`, `image_digests`, `policy_bundle_hash`, `skill_bundle_hash`, `action_contract_hash`, `model_adapter`, `events`

## Dashboard themes (CONFIRMED)

Workflow lead time; Safety denies; Quality gates; AEO layers; Cost; Drift

## Constraints

- No secrets in telemetry payloads
- Audit completeness 100% for success declaration
- Tenant labels required

## Open decisions

- Exact backend trio (Prometheus/Loki/Tempo vs alternatives) per profile — PROPOSED in values skeleton

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §9
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.6

## Status

CONFIRMED requirements / NOT IMPLEMENTED

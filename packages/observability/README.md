# packages/observability

## Purpose

Shared OTel helpers and trace envelope utilities (future).

## Scope

Libraries only; dashboards elsewhere.

## Current decision

PROPOSED.

## Constraints

- No secrets in spans
- tenant_id/run_id required labels

## Open decisions

- SDK choices — OPEN DECISION

## Source specification references

- k3s §9

## Status

W0: conventions + attribute registry + validation harness present (ADR-0016).
w2-00: uv workspace member (`saena-observability`, empty scaffold). Runtime
logging/trace implementation NOT IMPLEMENTED — arrives in unit w2-06;
exporter/collector stack deployment remains W2C.

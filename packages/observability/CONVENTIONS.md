# Telemetry conventions — packages/observability

Human-readable summary of ADR-0016 (telemetry conventions & attribute
registry). The registry files in `packages/observability/registry/` are the
machine-checked source of truth (SSOT); this document explains how to read
and use them. For the architecture-doc cross-linked form, see
`docs/architecture/observability-conventions.md`.

## Scope reminder

This package holds **conventions + a machine-validated registry** only.
Stack deployment (OTel Collector + Prometheus/Loki/Tempo + Grafana,
Alertmanager webhook adapter) is **W2C** — nothing in this package changes
runtime behavior in Wave 0.

## Span naming

`saena.<capability>.<operation>` — low-cardinality segments only.
Identifiers such as `run_id` or `tenant_id` must never be embedded in a span
name; they belong exclusively in attributes. This mirrors the same
low-cardinality-in-names / identifiers-as-attributes rule that ADR-0013
uses for event naming.

## Log format

Structured JSON, one line per record, using OTel Logs Data Model field
names:

- `timestamp` (RFC3339 UTC)
- `severity_text`
- `body`
- `trace_id`
- `span_id`

plus the same `saena.*` required-attribute set that applies to spans
(`saena.tenant_id`, `saena.run_id`, `saena.engine_id`, `saena.context`,
each subject to the per-context rules in the registry).

## Metric naming

`saena.<domain>.<name>`, using UCUM units. Prometheus name transforms
(e.g. `_total` suffixing) are **out of scope for W0** — that mapping is a
W2C exporter responsibility. W0 defines OTel-native metric names only.

## Correlation (trace / log / event, 3-way)

All three signal types correlate through a single shared `trace_id`. The
event envelope's `trace_id` field (ADR-0013, 9-field envelope) is the same
value carried by the OTel trace and by structured log records emitted
during that trace. There is no separate correlation ID scheme.

## Registry = machine SSOT

- `packages/observability/registry/attributes.schema.json` — JSON Schema
  2020-12 definition of a valid registry entry.
- `packages/observability/registry/attributes.yaml` — the human-edited
  attribute registry (name, type, cardinality, PII flag, per-context
  requirement rule, description).
- `packages/observability/registry/attributes.json` — generated mirror of
  `attributes.yaml`, kept in sync manually until W1 introduces registry
  codegen. Tests validate against this JSON mirror (see below).
- `packages/observability/registry/redaction-rules.yaml` — allowlist-first
  export policy plus a secret/PII denylist and structural violation rules
  (e.g. `V-AGG-TENANT`: `saena.tenant_id`/`saena.run_id` must never appear
  in `aggregate`-context telemetry).

Any new `saena.*` attribute must be added to `attributes.yaml` **and**
`attributes.json` in the same patch unit, and must validate against
`attributes.schema.json`. Context rules (`required`/`optional`/`forbidden`
per `tenant`/`system`/`aggregate`) must stay consistent with the envelope
`context_type` discriminator (ADR-0013) — this registry does not define a
second, divergent context vocabulary.

## Redaction — allowlist-first

Export policy is allowlist-first: only attributes registered here are
eligible for export at all. On top of that, `redaction-rules.yaml` layers a
secret/PII regex denylist (tokens, passwords, authorization headers, API
keys, bearer schemes, email-like values) as defense in depth, plus explicit
structural violation rules for context/attribute combinations that must
never co-occur (see `V-AGG-TENANT`).

Exporter-level enforcement (wiring these rules into an actual OTel
Collector processor) is a **W2C** deliverable. W0 delivers the rule
definitions and a test harness that validates the registry and rule
consistency; it does not change any running system.

## Validation

Run from the repository root:

```
uv run pytest packages/observability -q
uv run check-jsonschema --check-metaschema packages/observability/registry/attributes.schema.json
```

Tests in `packages/observability/tests/test_registry.py` validate every
registry entry against the schema and assert that a planted violation
fixture (an entry that wrongly marks `aggregate: required` for
`saena.tenant_id`) is correctly detected as inconsistent with the
tenant/run-id-forbidden-in-aggregate rule.

## Source of truth

- `docs/decisions/ADR-0016-telemetry-conventions.md`
- `docs/decisions/ADR-0013-event-envelope-v1.md`

# Observability conventions (telemetry attribute registry)

## Purpose

Executable telemetry conventions for the `saena.*` custom attribute
namespace, and the machine-validated registry that enforces them. This
document is the architecture-doc cross-link for
`packages/observability/CONVENTIONS.md`; see that file's colocated form for
the same content next to the registry it describes. General observability
requirements (dashboards, run trace envelope, stack rendering, retention)
remain in `docs/architecture/observability.md` and are not restated or
modified here.

## Scope

In: `saena.*` attribute namespace, span/log/metric naming rules,
envelope-derived context requirement rules, registry structure, redaction
policy. Out: Collector/backend deployment topology (W2C), Prometheus name
transforms (W2C exporter), dashboard design (`observability.md`'s six
confirmed dashboard themes are unchanged by this document).

## Current decision

CONFIRMED (ADR-0016, accepted 2026-07-12). Registry + conventions ship in
Wave 0; the OTel stack (Collector + Prometheus/Loki/Tempo + Grafana) ships
in W2C per `observability.md`'s "Rendering" decision — this document does
not change runtime behavior.

## Span naming

`saena.<capability>.<operation>` — low-cardinality only. Identifiers
(`run_id`, `tenant_id`, etc.) are attributes, never name segments.

## Required attributes (all spans)

`saena.tenant_id`, `saena.run_id`, `saena.engine_id`, `saena.context`
(`tenant`\|`system`\|`aggregate`), each subject to the per-context
requirement rules recorded in the registry (see below) and derived from the
event envelope's `context_type` discriminator (ADR-0013) — the envelope is
the single source for these rules; this document does not define a second,
divergent vocabulary.

## Logs

Structured JSON, one line, OTel Logs Data Model field names: `timestamp`
(RFC3339 UTC), `severity_text`, `body`, `trace_id`, `span_id`, plus the same
`saena.*` required-attribute set used for spans.

## Metrics

`saena.<domain>.<name>` + UCUM units. Prometheus name transforms (e.g.
`_total`) are deferred to the W2C exporter; W0 defines OTel-native names
only.

## Correlation

Trace / log / event 3-way correlation is established by sharing one
`trace_id` value across all three signal types, aligned with the event
envelope's `trace_id` field (ADR-0013, k3s §9.1 run trace envelope).

## Registry (machine SSOT)

`packages/observability/registry/`:

- `attributes.schema.json` — JSON Schema 2020-12 definition of a registry
  entry (`$id`:
  `https://schemas.the-saena.ai/common/observability-attribute-registry/v1/attributes.schema.json`).
- `attributes.yaml` — human-edited attribute registry (name, type,
  cardinality, PII flag, per-context rule, description).
- `attributes.json` — generated mirror of `attributes.yaml`, manually
  synced until W1 registry codegen lands.
- `redaction-rules.yaml` — allowlist-first export policy + secret/PII
  denylist + structural violation rules (`V-AGG-TENANT`:
  `saena.tenant_id`/`saena.run_id` forbidden under `aggregate` context).

Registry changes are within `packages/observability`'s single-owner
boundary (ADR-0016 constraints; CLAUDE.md principle 7 analog for
contractual-but-not-schema artifacts).

## Redaction

Allowlist-first: only registered attributes are export-eligible at all.
Denylist regex patterns (token, password, authorization, api key, bearer,
email-like) provide defense in depth on top of the allowlist. Aggregate
context containing `saena.tenant_id` or `saena.run_id` is a violation
(`V-AGG-TENANT`) per ADR-0006 rev.2's re-identification-prevention
requirement, structured per ADR-0013's `context_type` table.

## CI enforcement (W0 scope)

W0 delivers the registry schema, initial entries, redaction rule
definitions, and a pytest harness
(`packages/observability/tests/test_registry.py`) that validates every
entry against the schema and asserts a planted-violation fixture is
correctly rejected. Wiring these rules into an actual CI lint stage and
OTel Collector exporter is tracked as W2C / ADR-0018 gate-matrix follow-up
(see ADR-0016 "CI 강제" row and "Open decisions").

## Constraints

- No secrets in telemetry payloads (unchanged from `observability.md`).
- `saena.context` values and the envelope `context_type` discriminator use
  identical vocabulary — no separate vocabulary permitted (ADR-0016).
- Registry edits stay within `packages/observability` ownership.

## Source specification references

- `docs/decisions/ADR-0016-telemetry-conventions.md`
- `docs/decisions/ADR-0013-event-envelope-v1.md`
- `docs/architecture/observability.md` (general observability requirements,
  unchanged, not edited by this document)

## Status

CONFIRMED conventions + registry / stack rendering NOT IMPLEMENTED (W2C)

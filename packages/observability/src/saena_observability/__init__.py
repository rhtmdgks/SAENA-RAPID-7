"""saena_observability — tenant-safe logging, trace propagation, redaction (ADR-0016).

Public API surface (Wave 2 runtime, unit w2-06):

- `saena_observability.context` — `TelemetryContext`, `bind_telemetry_context`,
  `current_telemetry_context` (ADR-0016 required-attribute binding,
  ADR-0013 context rules).
- `saena_observability.registry` — read-only loader for the W0 attribute
  registry (`attributes.json`) and redaction rules (`redaction-rules.yaml`).
- `saena_observability.redaction` — allowlist-first redaction engine
  (`decide_redaction`, `redact_attributes`).
- `saena_observability.logging` — `get_logger`, `SaenaJsonFormatter`
  (single-line structured JSON logs with implicit context pickup).
- `saena_observability.trace` — trace_id/span_id validation & generation,
  W3C traceparent parse/build, `current_trace_id` for 3-way correlation.
- `saena_observability.naming` — `saena.<capability>.<operation>` span-name
  and `saena.<domain>.<name>` metric-name validators.
- `saena_observability.attributes` — `set_redacted_attribute(s)`, an OTel
  `Span.set_attribute` wrapper routed through redaction.

This package must not import `saena_domain` (import-linter enforced,
`observability-below-services` / boundary rules in `.importlinter`).
"""

from saena_observability.context import (
    TelemetryContext,
    bind_telemetry_context,
    current_telemetry_context,
)
from saena_observability.logging import SaenaJsonFormatter, get_logger
from saena_observability.redaction import (
    RedactionAction,
    RedactionDecision,
    decide_redaction,
    redact_attributes,
)
from saena_observability.trace import (
    TraceParent,
    build_traceparent,
    current_span_id,
    current_trace_id,
    generate_span_id,
    generate_trace_id,
    is_valid_span_id,
    is_valid_trace_id,
    parse_traceparent,
)

__all__ = [
    "TelemetryContext",
    "bind_telemetry_context",
    "current_telemetry_context",
    "SaenaJsonFormatter",
    "get_logger",
    "RedactionAction",
    "RedactionDecision",
    "decide_redaction",
    "redact_attributes",
    "TraceParent",
    "build_traceparent",
    "current_span_id",
    "current_trace_id",
    "generate_span_id",
    "generate_trace_id",
    "is_valid_span_id",
    "is_valid_trace_id",
    "parse_traceparent",
]

__version__ = "0.1.0"

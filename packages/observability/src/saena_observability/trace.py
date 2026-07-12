"""Trace ID validation, generation, and W3C traceparent propagation.

`trace_id` is the 3-way correlation key shared by the event envelope
(ADR-0013, 32-hex string field), OTel spans, and structured logs (ADR-0016
"Correlation" row). This module provides:

- `is_valid_trace_id` / `is_valid_span_id` — validate the envelope's
  32-hex-lowercase (16-hex for span) format.
- `generate_trace_id` / `generate_span_id` — produce new valid IDs using the
  OTel SDK's ID generator (avoids the all-zero invalid ID OTel reserves).
- `parse_traceparent` / `build_traceparent` — W3C Trace Context header
  (`00-<trace_id>-<span_id>-<flags>`) parse/build.
- `current_trace_id` — resolves the trace_id from the current OTel span
  context, for 3-way correlation with envelope/log records.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from opentelemetry import trace as otel_trace
from opentelemetry.trace import format_span_id, format_trace_id
from opentelemetry.trace.span import INVALID_SPAN_ID, INVALID_TRACE_ID

_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID_RE = re.compile(r"^[0-9a-f]{16}$")

_TRACEPARENT_VERSION = "00"
_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)


def is_valid_trace_id(value: str) -> bool:
    """True iff `value` is 32 lowercase hex chars and not the all-zero ID."""
    return bool(_TRACE_ID_RE.match(value)) and value != "0" * 32


def is_valid_span_id(value: str) -> bool:
    """True iff `value` is 16 lowercase hex chars and not the all-zero ID."""
    return bool(_SPAN_ID_RE.match(value)) and value != "0" * 16


def generate_trace_id() -> str:
    """Generate a new valid 32-hex-lowercase trace_id via the OTel SDK RNG."""
    from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

    trace_id = RandomIdGenerator().generate_trace_id()
    return format_trace_id(trace_id)


def generate_span_id() -> str:
    """Generate a new valid 16-hex-lowercase span_id via the OTel SDK RNG."""
    from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

    span_id = RandomIdGenerator().generate_span_id()
    return format_span_id(span_id)


@dataclass(frozen=True, slots=True)
class TraceParent:
    """Parsed W3C `traceparent` header value."""

    version: str
    trace_id: str
    span_id: str
    flags: str

    def is_sampled(self) -> bool:
        return bool(int(self.flags, 16) & 0x01)


def parse_traceparent(header_value: str) -> TraceParent:
    """Parse a W3C `traceparent` header: `00-<trace_id>-<span_id>-<flags>`.

    Raises `ValueError` if the header does not match the expected shape or
    carries an invalid (all-zero) trace_id/span_id, per the W3C Trace
    Context spec's validity rules.
    """
    match = _TRACEPARENT_RE.match(header_value)
    if match is None:
        raise ValueError(f"malformed traceparent header: {header_value!r}")
    trace_id = match.group("trace_id")
    span_id = match.group("span_id")
    if not is_valid_trace_id(trace_id):
        raise ValueError(f"traceparent has invalid (all-zero) trace_id: {header_value!r}")
    if not is_valid_span_id(span_id):
        raise ValueError(f"traceparent has invalid (all-zero) span_id: {header_value!r}")
    return TraceParent(
        version=match.group("version"),
        trace_id=trace_id,
        span_id=span_id,
        flags=match.group("flags"),
    )


def build_traceparent(trace_id: str, span_id: str, *, sampled: bool = True) -> str:
    """Build a W3C `traceparent` header value from trace_id/span_id.

    Raises `ValueError` if `trace_id`/`span_id` are not valid per
    `is_valid_trace_id` / `is_valid_span_id`.
    """
    if not is_valid_trace_id(trace_id):
        raise ValueError(f"invalid trace_id: {trace_id!r}")
    if not is_valid_span_id(span_id):
        raise ValueError(f"invalid span_id: {span_id!r}")
    flags = "01" if sampled else "00"
    return f"{_TRACEPARENT_VERSION}-{trace_id}-{span_id}-{flags}"


def current_trace_id() -> str | None:
    """Return the `trace_id` of the current OTel span context, or `None`.

    Used for 3-way correlation: the same value is expected to appear in the
    event envelope's `trace_id` field (ADR-0013) and in structured log
    records emitted during the same trace (ADR-0016 "Correlation" row).
    """
    span = otel_trace.get_current_span()
    ctx = span.get_span_context()
    if ctx is None or ctx.trace_id == INVALID_TRACE_ID or not ctx.is_valid:
        return None
    return format_trace_id(ctx.trace_id)


def current_span_id() -> str | None:
    """Return the `span_id` of the current OTel span context, or `None`."""
    span = otel_trace.get_current_span()
    ctx = span.get_span_context()
    if ctx is None or ctx.span_id == INVALID_SPAN_ID or not ctx.is_valid:
        return None
    return format_span_id(ctx.span_id)

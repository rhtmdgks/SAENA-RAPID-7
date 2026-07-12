"""Structured single-line JSON logging (ADR-0016 "로그" row).

Emits one JSON object per log record with OTel Logs Data Model field names
(`timestamp`, `severity`, `body`) plus the `saena.*` required-attribute set
picked up implicitly from the currently bound `TelemetryContext`
(`saena_observability.context.bind_telemetry_context`). Attributes are
routed through the redaction engine (`saena_observability.redaction`)
before being written — non-allowlisted or context-violating keys never
reach the emitted line, and secret-pattern-matching values are replaced
with `REDACTED_VALUE`.

`body` (the formatted log message, `record.getMessage()`) is free text —
it is NOT covered by the allowlist model (there is no "attribute name" for
a log message), but it CAN contain a secret via string interpolation
(``logger.info("token=%s", token)`` or an f-string built by the caller).
`body` is therefore scrubbed through `saena_observability.redaction.
redact_text`, which applies every VALUE-applicable denylist pattern
against the message text and replaces only the matched substring — the
rest of the message is preserved.

Context rules (ADR-0016/ADR-0013): `saena.context="system"` or
`"aggregate"` records carry no `saena.tenant_id` / `saena.run_id` KEY at
all (property-level absence — not `null`). This is enforced upstream by
`bind_telemetry_context`, which refuses to bind a forbidden combination,
and reinforced here by only emitting keys whose value is not `None`.

Caveat — stdlib `logging`'s `extra=` mapping: `logging.LogRecord.__init__`
silently drops any `extra` key that collides with a reserved `LogRecord`
attribute name (`message`, `args`, `levelname`, `msg`, etc. — see stdlib
`logging` source, `makeRecord`/`LogRecord.__init__`). This module reads
the `saena_attributes` extra key specifically (a name deliberately chosen
to avoid any stdlib collision), but callers should be aware that stdlib
logging's `extra=` mechanism as a whole has this silent-drop behavior for
any *other* colliding key they might pass — it is a stdlib limitation, not
something this formatter can detect or warn about after the fact.
"""

from __future__ import annotations

import json
import logging as _stdlib_logging
from datetime import UTC, datetime
from typing import Any

from saena_observability.context import current_telemetry_context
from saena_observability.redaction import redact_attributes, redact_text
from saena_observability.trace import current_span_id, current_trace_id


def _rfc3339_z(dt: datetime) -> str:
    """Format `dt` as RFC3339 UTC with a `Z` suffix (ADR-0013 rev.2 ②
    canonicalization: `Z`-terminated only, no `+00:00` offset form)."""
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _context_attributes() -> dict[str, Any]:
    """Build the raw `saena.*` attribute dict from the bound context.

    Keys whose value is `None` are omitted entirely (property-level
    absence per ADR-0016/ADR-0013 — a system/aggregate-context record must
    not carry a `saena.tenant_id`/`saena.run_id` key even with a null
    value).
    """
    ctx = current_telemetry_context()
    if ctx is None:
        return {}
    raw: dict[str, Any] = {"saena.context": ctx.context}
    if ctx.tenant_id is not None:
        raw["saena.tenant_id"] = ctx.tenant_id
    if ctx.run_id is not None:
        raw["saena.run_id"] = ctx.run_id
    if ctx.engine_id is not None:
        raw["saena.engine_id"] = ctx.engine_id
    return raw


class SaenaJsonFormatter(_stdlib_logging.Formatter):
    """`logging.Formatter` emitting single-line redacted structured JSON.

    Use via `get_logger()` below, or attach directly to any
    `logging.Handler` for interop with existing stdlib-logging call sites.
    """

    def format(self, record: _stdlib_logging.LogRecord) -> str:
        ctx = current_telemetry_context()
        context_value = ctx.context if ctx is not None else None

        payload: dict[str, Any] = {
            "timestamp": _rfc3339_z(datetime.fromtimestamp(record.created, tz=UTC)),
            "severity": record.levelname,
            "body": redact_text(record.getMessage()),
        }

        trace_id = current_trace_id()
        span_id = current_span_id()
        if trace_id is not None:
            payload["trace_id"] = trace_id
        if span_id is not None:
            payload["span_id"] = span_id

        extra_attrs = getattr(record, "saena_attributes", None)
        raw_attrs = _context_attributes()
        if isinstance(extra_attrs, dict):
            raw_attrs.update(extra_attrs)

        payload.update(redact_attributes(raw_attrs, context=context_value))

        return json.dumps(payload, sort_keys=True, default=str)


def configure_handler(handler: _stdlib_logging.Handler) -> _stdlib_logging.Handler:
    """Attach a `SaenaJsonFormatter` to `handler` and return it."""
    handler.setFormatter(SaenaJsonFormatter())
    return handler


def get_logger(name: str, *, level: int = _stdlib_logging.INFO) -> _stdlib_logging.Logger:
    """Return a `logging.Logger` configured with `SaenaJsonFormatter`.

    Idempotent: calling this repeatedly with the same `name` does not stack
    duplicate handlers.
    """
    logger = _stdlib_logging.getLogger(name)
    logger.setLevel(level)
    already_configured = any(isinstance(h.formatter, SaenaJsonFormatter) for h in logger.handlers)
    if not already_configured:
        handler = _stdlib_logging.StreamHandler()
        configure_handler(handler)
        logger.addHandler(handler)
    logger.propagate = False
    return logger

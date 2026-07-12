"""OTel span attribute-setting wrapper, routed through redaction (ADR-0016).

`opentelemetry.trace.Span.set_attribute` has no awareness of the
`saena.*` registry or redaction rules — this module wraps it so that no
call site can bypass the allowlist-first redaction engine
(`saena_observability.redaction`) when attaching a `saena.*` attribute to a
span.
"""

from __future__ import annotations

from typing import Any

from opentelemetry.trace import Span

from saena_observability.context import TelemetryContext, current_telemetry_context
from saena_observability.redaction import RedactionAction, decide_redaction


def set_redacted_attribute(
    span: Span,
    name: str,
    value: Any,
    *,
    telemetry_context: TelemetryContext | None = None,
) -> RedactionAction:
    """Set `name`=`value` on `span`, applying the redaction engine first.

    `telemetry_context` defaults to the currently bound context
    (`current_telemetry_context()`); its `context` field (tenant/system/
    aggregate) is used to evaluate structural violation rules such as
    V-AGG-TENANT. If no context is bound and none is passed explicitly,
    structural violation rules are skipped (allowlist + denylist rules
    still apply).

    Returns the `RedactionAction` that was applied, so callers can assert
    on it in tests without needing to inspect the span's internal state.
    """
    ctx = telemetry_context if telemetry_context is not None else current_telemetry_context()
    context_value = ctx.context if ctx is not None else None

    decision = decide_redaction(name, value, context=context_value)
    if decision.action is RedactionAction.ALLOW:
        span.set_attribute(name, value)
    elif decision.action is RedactionAction.REDACT_VALUE:
        from saena_observability.redaction import REDACTED_VALUE

        span.set_attribute(name, REDACTED_VALUE)
    # DROP: do not call set_attribute at all.
    return decision.action


def set_redacted_attributes(
    span: Span,
    attributes: dict[str, Any],
    *,
    telemetry_context: TelemetryContext | None = None,
) -> dict[str, RedactionAction]:
    """Apply `set_redacted_attribute` to every item in `attributes`.

    Returns a dict of attribute name -> `RedactionAction` applied.
    """
    return {
        name: set_redacted_attribute(span, name, value, telemetry_context=telemetry_context)
        for name, value in attributes.items()
    }

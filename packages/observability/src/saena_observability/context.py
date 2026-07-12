"""Telemetry context binding (ADR-0016 / ADR-0013 3-context model).

Binds ``saena.tenant_id``, ``saena.run_id``, ``saena.engine_id`` and
``saena.context`` onto a `contextvars.ContextVar` so that structured log
records (and, in future OTel-wired code, spans) can pick up the "current"
telemetry context implicitly without threading it through every call site.

Context rules are derived from the event envelope's `context_type`
discriminator (ADR-0013) — this module does not invent a second vocabulary;
`TelemetryContext.context` uses the same three values: ``tenant`` |
``system`` | ``aggregate``.

Per ADR-0016 / ADR-0013: in ``system`` and ``aggregate`` context, tenant_id
and run_id are not merely optional — they are *forbidden* (property-level
absence, never present-but-null). This module enforces that at bind time:
`bind_telemetry_context` raises `ValueError` if a caller attempts to bind a
non-tenant context together with tenant_id or run_id.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal

ContextType = Literal["tenant", "system", "aggregate"]

_FORBIDDEN_IDENTIFIERS_BY_CONTEXT: dict[ContextType, tuple[str, ...]] = {
    "tenant": (),
    "system": ("tenant_id", "run_id"),
    "aggregate": ("tenant_id", "run_id"),
}


@dataclass(frozen=True, slots=True)
class TelemetryContext:
    """Bound telemetry context for the current execution scope.

    Fields mirror the `saena.*` required-attribute set (ADR-0016):
    `saena.tenant_id`, `saena.run_id`, `saena.engine_id`, `saena.context`.
    `tenant_id` / `run_id` are `None` (i.e. absent) whenever `context` is
    `"system"` or `"aggregate"` — enforced by `bind_telemetry_context`, not
    by this dataclass alone, since a dataclass cannot express "must be
    None" as a type constraint.
    """

    context: ContextType
    tenant_id: str | None = None
    run_id: str | None = None
    engine_id: str | None = None


_current_context: ContextVar[TelemetryContext | None] = ContextVar(
    "saena_telemetry_context", default=None
)


def current_telemetry_context() -> TelemetryContext | None:
    """Return the currently bound `TelemetryContext`, or `None` if unbound."""
    return _current_context.get()


def _validate(ctx: TelemetryContext) -> None:
    forbidden = _FORBIDDEN_IDENTIFIERS_BY_CONTEXT[ctx.context]
    violations = []
    if "tenant_id" in forbidden and ctx.tenant_id is not None:
        violations.append("tenant_id")
    if "run_id" in forbidden and ctx.run_id is not None:
        violations.append("run_id")
    if violations:
        raise ValueError(
            f"saena.context={ctx.context!r} forbids the following identifiers "
            f"(ADR-0016/ADR-0013 context_type table): {violations} — pass None, "
            "do not bind them for this context."
        )
    if ctx.context == "tenant" and ctx.tenant_id is None:
        raise ValueError(
            "saena.context='tenant' requires saena.tenant_id (ADR-0016 required-attribute rule)."
        )


@contextmanager
def bind_telemetry_context(
    context: ContextType,
    *,
    tenant_id: str | None = None,
    run_id: str | None = None,
    engine_id: str | None = None,
) -> Iterator[TelemetryContext]:
    """Bind a `TelemetryContext` for the duration of the `with` block.

    Raises `ValueError` immediately (before binding) if the requested
    combination violates the ADR-0016/ADR-0013 context rules — e.g.
    `context="aggregate"` with a non-None `tenant_id`.
    """
    ctx = TelemetryContext(context=context, tenant_id=tenant_id, run_id=run_id, engine_id=engine_id)
    _validate(ctx)
    token: Token[TelemetryContext | None] = _current_context.set(ctx)
    try:
        yield ctx
    finally:
        _current_context.reset(token)

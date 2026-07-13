"""Execution-context separation and contextvars-based tenant propagation.

Spec basis: ADR-0006 rev.2 / ADR-0013 3-context model (tenant/system/
aggregate — mirrored here as execution-context dataclasses rather than event
envelope discriminator branches, since this module concerns in-process
propagation, not wire format) and ADR-0014's synchronous-path guard intent
(cross-tenant access target: 0, tenancy-model.md Constraints).

`bind_tenant`/`current_tenant`/`require_tenant` use `contextvars.ContextVar`,
which is copy-on-task-creation under asyncio — a value bound in one task is
never visible to a sibling task started afterwards unless explicitly copied,
giving the cross-tenant isolation this module is meant to help enforce.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

from saena_domain.identity.actor import ActorContext
from saena_domain.identity.errors import TenantMismatchError, UnboundTenantContextError
from saena_domain.identity.tenant import TenantContext


@dataclass(frozen=True, slots=True)
class TenantExecutionContext:
    """Execution context for tenant-scoped work — the common case.

    `tenant_id`/`run_id` are required on the event path for this context
    class (ADR-0013 `context_type: tenant` branch, `run_id` required per the
    rev.2 amendment closing that Open decision). `actor` is optional since
    not every tenant-scoped execution is actor-initiated (e.g. a scheduled
    worker acting on behalf of a tenant).
    """

    tenant: TenantContext
    run_id: str
    actor: ActorContext | None = None


@dataclass(frozen=True, slots=True)
class SystemExecutionContext:
    """Execution context for system-scoped work.

    Mirrors ADR-0013's `context_type: system` branch: `tenant_id`/`run_id`
    are not merely optional, they are structurally absent from this
    dataclass — a system execution never carries a tenant or a run.
    """

    producer: str
    actor: ActorContext | None = None


@dataclass(frozen=True, slots=True)
class AggregateExecutionContext:
    """Execution context for aggregate/de-identified work.

    Mirrors ADR-0013's `context_type: aggregate` branch: `tenant_id`/`run_id`
    are structurally absent (never carried, not merely optional) — original
    tenant lineage is retained only as an opaque, audit-role-only reference,
    matching the envelope's `lineage_audit_ref` field.
    """

    aggregate_scope_id: str
    cohort_size: int
    privacy_threshold: int
    lineage_audit_ref: str
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cohort_size < 1:
            raise ValueError(f"cohort_size must be >= 1, got {self.cohort_size}")
        if self.privacy_threshold < 1:
            raise ValueError(f"privacy_threshold must be >= 1, got {self.privacy_threshold}")


ExecutionContext = TenantExecutionContext | SystemExecutionContext | AggregateExecutionContext

_current_tenant_context: ContextVar[TenantContext] = ContextVar("saena_current_tenant_context")


@contextmanager
def bind_tenant(context: TenantContext) -> Iterator[TenantContext]:
    """Bind `context` as the current tenant for the duration of the `with`
    block (and any asyncio tasks spawned from within it, since
    `contextvars.Context` is copied at task-creation time).

    Always restores the previous binding (or unbinds entirely) on exit, even
    on exception — this is a `contextlib.contextmanager`, not a bare
    assignment, specifically so nested `bind_tenant` calls compose safely.
    """
    token: Token[TenantContext] = _current_tenant_context.set(context)
    try:
        yield context
    finally:
        _current_tenant_context.reset(token)


def current_tenant() -> TenantContext:
    """Return the currently bound `TenantContext`.

    Raises `UnboundTenantContextError` if called outside a `bind_tenant(...)`
    block in the current asyncio task / thread context — there is no
    implicit "default tenant" fallback, by design (tenancy-model.md
    Constraints: cross-tenant access target 0).
    """
    try:
        return _current_tenant_context.get()
    except LookupError as exc:
        raise UnboundTenantContextError(
            "current_tenant() called with no tenant bound via bind_tenant() "
            "in this execution context"
        ) from exc


def require_tenant(expected_tenant_id: str) -> TenantContext:
    """Cross-tenant guard: assert the currently bound tenant's `tenant_id`
    equals `expected_tenant_id`, returning the bound `TenantContext` on
    success.

    Raises `TenantMismatchError` on mismatch (never silently proceeds — same
    "no silent 200" posture ADR-0014 mandates for the HTTP reconciliation
    path). Raises `UnboundTenantContextError` (via `current_tenant()`) if no
    tenant is bound at all.
    """
    bound = current_tenant()
    actual = bound.tenant_id.value
    if actual != expected_tenant_id:
        raise TenantMismatchError(
            f"bound tenant {actual!r} does not match required tenant {expected_tenant_id!r}",
            context={"bound_tenant_id": actual, "expected_tenant_id": expected_tenant_id},
        )
    return bound

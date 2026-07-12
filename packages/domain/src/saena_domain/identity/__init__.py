"""saena_domain.identity — tenant/actor identity, execution-context
separation, and cross-tenant guards.

Spec basis: ADR-0014 (tenant propagation), ADR-0013 (event envelope context
types), docs/architecture/tenancy-model.md, docs/architecture/
contract-catalog.md (`TenantContext`/`ActorContext` rows). This package adds
runtime behaviour over the generated pydantic models in
`saena_schemas.context.{tenant_context_v1,actor_context_v1}` — it never
redefines those DTOs' fields.
"""

from __future__ import annotations

from saena_domain.identity.actor import ActorContext, ActorTenantRequiredError
from saena_domain.identity.errors import (
    EngineScopeError,
    IdentityError,
    InvalidTenantIdError,
    NamespaceDerivationError,
    NamespaceMismatchError,
    TenantMismatchError,
    TenantSuspendedError,
    TenantTerminatingError,
    UnboundTenantContextError,
)
from saena_domain.identity.execution_context import (
    AggregateExecutionContext,
    ExecutionContext,
    SystemExecutionContext,
    TenantExecutionContext,
    bind_tenant,
    current_tenant,
    require_tenant,
)
from saena_domain.identity.http import (
    TENANT_ENV_VAR_NAME,
    TENANT_HEADER_NAME,
    reconcile_tenant,
)
from saena_domain.identity.tenant import (
    TenantContext,
    TenantId,
    derive_namespace,
    validate_namespace,
)

__all__ = [
    "TENANT_ENV_VAR_NAME",
    "TENANT_HEADER_NAME",
    "ActorContext",
    "ActorTenantRequiredError",
    "AggregateExecutionContext",
    "EngineScopeError",
    "ExecutionContext",
    "IdentityError",
    "InvalidTenantIdError",
    "NamespaceDerivationError",
    "NamespaceMismatchError",
    "SystemExecutionContext",
    "TenantContext",
    "TenantExecutionContext",
    "TenantId",
    "TenantMismatchError",
    "TenantSuspendedError",
    "TenantTerminatingError",
    "UnboundTenantContextError",
    "bind_tenant",
    "current_tenant",
    "derive_namespace",
    "reconcile_tenant",
    "require_tenant",
    "validate_namespace",
]

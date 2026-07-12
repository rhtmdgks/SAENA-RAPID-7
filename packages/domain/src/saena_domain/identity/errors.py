"""Exception hierarchy for `saena_domain.identity`.

All errors here are *domain* errors: they carry structured data describing
what invariant was violated but they never format HTTP responses themselves
(problem-detail mapping — see `packages/contracts/json-schema/common/
problem-detail/v1/problem-detail.schema.json`, ADR-0015 — is a services-layer
concern). `error_code` values on each exception follow the
`saena.<category>.<reason>` pattern used by that contract so a services-layer
mapper can reuse them verbatim.
"""

from __future__ import annotations

from typing import Any


class IdentityError(Exception):
    """Base class for every error raised by `saena_domain.identity`.

    Attributes:
        error_code: `saena.<category>.<reason>` taxonomy string (ADR-0015),
            reusable verbatim as a services-layer ProblemDetail `error_code`.
        context: structured, log-safe data describing the violation. Callers
            building an audit event or a 403 response read this dict rather
            than parsing the exception message.
    """

    error_code: str = "saena.identity.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class InvalidTenantIdError(IdentityError):
    """`tenant_id` does not match the ADR-0014 slug pattern."""

    error_code = "saena.identity.invalid_tenant_id"


class NamespaceDerivationError(IdentityError):
    """A derived namespace would exceed the 63-char k3s namespace limit."""

    error_code = "saena.identity.namespace_derivation_failed"


class NamespaceMismatchError(IdentityError):
    """`TenantContext.namespace` does not equal the value derived from
    `tenant_id` (ADR-0014 Constraints:65 — namespace is a computed field,
    never an independent input; mismatch is a hard error at the runtime
    layer since JSON Schema cannot express this cross-field invariant —
    see tenant-context.schema.json's `namespace` property `$comment` and the
    `namespace-mismatch` permanent gap fixture).
    """

    error_code = "saena.identity.namespace_mismatch"


class TenantSuspendedError(IdentityError):
    """`TenantContext.status` is not `active` (ADR-0014 status enum)."""

    error_code = "saena.identity.tenant_suspended"


class TenantTerminatingError(TenantSuspendedError):
    """`TenantContext.status == "terminating"`.

    Subclasses `TenantSuspendedError` so callers that only guard against the
    general "not usable" case can catch the parent class, while callers that
    need to distinguish terminating tenants specifically may catch this.
    """

    error_code = "saena.identity.tenant_terminating"


class EngineScopeError(IdentityError):
    """Requested `engine_id` is outside `TenantContext.engine_scope`, or a
    non-`chatgpt-search` engine was requested at all (CLAUDE.md Engine scope
    v1: ChatGPT Search only; ADR-0013:58 closed engine_id enum).
    """

    error_code = "saena.identity.engine_scope_denied"


class TenantMismatchError(IdentityError):
    """Cross-tenant guard violation.

    Raised by `require_tenant()` (contextvar cross-tenant guard) and by
    `reconcile_tenant()` (ADR-0014 synchronous HTTP path: `X-Saena-Tenant-Id`
    header vs. `SAENA_TENANT_ID` pod env mismatch). ADR-0014 Constraints:64
    forbids silently ignoring or 200-ing a mismatch — the services layer maps
    this exception to HTTP 403 + an audit event, using `.context` as the
    audit payload (it records which two values disagreed, never any secret
    material).
    """

    error_code = "saena.identity.tenant_mismatch"


class UnboundTenantContextError(IdentityError):
    """`current_tenant()` was called with no tenant bound in this context
    (i.e. outside a `bind_tenant(...)` block) in the current asyncio task /
    thread context.
    """

    error_code = "saena.identity.tenant_context_unbound"

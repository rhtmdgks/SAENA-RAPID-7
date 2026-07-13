"""Exception hierarchy for `saena_entity_resolution`.

Follows the same shape as `saena_site_discovery.errors` /
`saena_domain.execution.errors`: every exception carries an `error_code`
(`saena.<category>.<reason>`, ADR-0015 taxonomy) and a structured, log-safe
`.context` dict. `to_job_error()` additionally renders the exception as a
`saena_domain.execution.job_error.JobError` value object (reusing the SAME
canonical error model the shared execution-domain layer defines, rather than
inventing a second one) — every `error_code` below is chosen so its category
segment is one of `JobError.KNOWN_ERROR_CATEGORIES`, so `to_job_error()`
never itself raises `JobErrorValidationError`.
"""

from __future__ import annotations

from typing import Any

from saena_domain.execution import JobError


class EntityResolutionError(Exception):
    """Base class for every error raised by `saena_entity_resolution`."""

    error_code: str = "saena.internal.entity_resolution_error"
    retryable: bool = False

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), **self.context}

    def to_job_error(self) -> JobError:
        """Render this exception as a canonical `JobError` (ADR-0015),
        truncated to `JobError`'s own 500-char summary bound."""
        return JobError(
            error_code=self.error_code,
            summary=str(self)[:500],
            retryable=self.retryable,
        )


class CompetitorOwnershipDeniedError(EntityResolutionError):
    """A caller attempted to mark a `competitor` entity as `owned` (or
    otherwise attribute first-party ownership to it).

    Fail-closed ownership rule (w4-03 mission: "a competitor entity is NEVER
    marked as owned/first-party. ... the module must refuse to attribute
    ownership to a competitor entity"). This is a hard `ValueError`-class
    domain error, never a silent downgrade/coercion of the requested
    `entity_type` or `is_owned` flag.
    """

    error_code = "saena.validation.competitor_ownership_denied"


class AliasConflictError(EntityResolutionError):
    """Two aliases in the same canonicalization request resolve to
    incompatible entity attributes (e.g. the same alias string mapped to two
    different `entity_type`/`is_owned` combinations, or the same
    `entity_id` claimed by two different canonical names) — fail closed
    rather than silently picking one side."""

    error_code = "saena.validation.alias_conflict"


class EmptyAliasSetError(EntityResolutionError):
    """A canonicalization request supplied zero aliases for an entity —
    there is nothing to canonicalize."""

    error_code = "saena.validation.empty_alias_set"


class CrossTenantEntityAccessError(EntityResolutionError):
    """A caller attempted to store or read an `EntityRecord` (or the graph it
    belongs to) under a `tenant_id` different from the one it was resolved
    for (fail closed — mirrors `saena_site_discovery.errors.
    CrossTenantObservationError` / `saena_artifact_registry.blobstore`'s
    cross-tenant gating discipline)."""

    error_code = "saena.auth.cross_tenant_denied"


class EntityGraphNotFoundError(EntityResolutionError):
    """No stored entity graph exists for the requested `(tenant_id,
    project_id)` key."""

    error_code = "saena.not_found.entity_graph"


__all__ = [
    "AliasConflictError",
    "CompetitorOwnershipDeniedError",
    "CrossTenantEntityAccessError",
    "EmptyAliasSetError",
    "EntityGraphNotFoundError",
    "EntityResolutionError",
]

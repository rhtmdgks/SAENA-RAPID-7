"""Exception hierarchy for `saena_demand_graph`.

Follows the same shape as `saena_site_discovery.errors` /
`saena_domain.execution.errors`: every exception carries an `error_code`
(`saena.<category>.<reason>`, ADR-0015 taxonomy) and a structured, log-safe
`.context` dict. `saena_demand_graph` does not build `saena_domain.execution.
job_error.JobError` values (this package is not a `JobKind`-scoped
crawl/execution pass — it is a pure deterministic builder over already-
approved in-memory input), so unlike `saena_site_discovery.errors` there is
no `to_job_error()` rendering here; callers that need a `JobError` shape can
construct one directly from `.error_code`/`str(exc)`/`.retryable`.
"""

from __future__ import annotations

from typing import Any


class DemandGraphError(Exception):
    """Base class for every error raised by `saena_demand_graph`."""

    error_code: str = "saena.internal.demand_graph_error"
    retryable: bool = False

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), **self.context}


class MaterialValidationError(DemandGraphError):
    """A `FirstPartyMaterial` input item failed validation at construction
    time (e.g. empty text, disallowed source kind, non-first-party
    provenance)."""

    error_code = "saena.validation.first_party_material_invalid"


class EmptyMaterialSetError(DemandGraphError):
    """`build_demand_graph` was called with zero approved first-party
    materials — a demand graph cannot be built from nothing, and silently
    returning an empty graph would hide an upstream data-supply bug rather
    than surfacing it."""

    error_code = "saena.validation.empty_material_set"


class UnknownIntentError(DemandGraphError):
    """A `FirstPartyMaterial` could not be mapped to any of the CONFIRMED
    intent labels (Algorithm spec §3.1 Query Cluster `intent` field) by this
    package's deterministic keyword classifier — raised rather than silently
    defaulting to an arbitrary intent, so an unlabelled input is always a
    visible, fixable data problem."""

    error_code = "saena.validation.unknown_intent"


class CrossTenantDemandGraphError(DemandGraphError):
    """A caller attempted to store or read a `DemandGraph` under a
    `tenant_id` different from the one it was built under (fail closed —
    mirrors `saena_site_discovery.errors.CrossTenantObservationError`'s
    cross-tenant gating discipline)."""

    error_code = "saena.auth.cross_tenant_denied"


class DemandGraphNotFoundError(DemandGraphError):
    """No stored `DemandGraph` exists for the requested `(tenant_id,
    project_id)` key."""

    error_code = "saena.not_found.demand_graph"


class EngineNotPermittedError(DemandGraphError):
    """A caller supplied an `engine_id` outside the v1 closed engine scope
    (CLAUDE.md "Engine scope (v1)": chatgpt-search ONLY — Google AIO/AI-Mode/
    Gemini forbidden everywhere, including this package's own optional
    `engine_id` passthrough to the emitted event payload)."""

    error_code = "saena.policy_denied.engine_not_permitted"


__all__ = [
    "CrossTenantDemandGraphError",
    "DemandGraphError",
    "DemandGraphNotFoundError",
    "EmptyMaterialSetError",
    "EngineNotPermittedError",
    "MaterialValidationError",
    "UnknownIntentError",
]

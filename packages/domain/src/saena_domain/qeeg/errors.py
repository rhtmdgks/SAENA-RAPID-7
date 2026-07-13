"""Exception hierarchy for `saena_domain.qeeg` (w4-11).

Mirrors `saena_claim_evidence.errors`' shape (stable `error_code`, structured
log-safe `.context` — never raw claim/evidence text): this module is a
READ-ONLY projection over claim-evidence's write-model, so its own errors
never echo `claim_text`/`excerpt` content back into a log line, only
identifiers (`claim_id`, `evidence_id`, `entity_id`, `tenant_id`).
"""

from __future__ import annotations

from typing import Any


class QeegProjectionError(Exception):
    """Base class for every error raised by `saena_domain.qeeg`."""

    error_code: str = "saena.internal.qeeg_projection_error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), **self.context}


class CrossTenantProjectionAccessError(QeegProjectionError):
    """A caller attempted to fold an event into, or query, a projection under
    a `tenant_id` different from the one the projection (or the event being
    folded) was scoped to — fail closed, default-DENY, mirrors
    `saena_claim_evidence.errors.CrossTenantLedgerAccessError` exactly. A
    QEEG projection built for one tenant never silently absorbs, or answers
    queries about, another tenant's events."""

    error_code = "saena.auth.cross_tenant_denied"


class UnknownClaimError(QeegProjectionError):
    """A caller queried a `claim_id` the projection has never observed (via
    replay) for the requested `(tenant_id, project_id)` scope."""

    error_code = "saena.not_found.qeeg_claim"


class UnknownEntityError(QeegProjectionError):
    """A caller queried an `entity_id` the projection has never observed
    (via replay) for the requested `(tenant_id, project_id)` scope."""

    error_code = "saena.not_found.qeeg_entity"


__all__ = [
    "CrossTenantProjectionAccessError",
    "QeegProjectionError",
    "UnknownClaimError",
    "UnknownEntityError",
]

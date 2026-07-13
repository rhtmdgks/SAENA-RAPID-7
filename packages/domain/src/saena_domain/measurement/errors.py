"""Exception hierarchy for `saena_domain.measurement` (w5-09).

Follows the same shape as `saena_domain.persistence.errors` /
`saena_vector_store.errors` (`saena.<category>.<reason>` `error_code` +
structured, log-safe `context` dict — ADR-0015 canonical error model), so a
services-layer ProblemDetail mapper reuses these verbatim.

Every idempotency-violation error here is FAIL-CLOSED: it is raised INSTEAD of
silently choosing a winner or overwriting stored state — the store's already-
persisted content is always the FIRST accepted content (see
`saena_domain.measurement.ports` module docstring "Idempotency model").
"""

from __future__ import annotations

from typing import Any


class MeasurementError(Exception):
    """Base class for every error raised by `saena_domain.measurement`.

    Attributes:
        error_code: `saena.<category>.<reason>` taxonomy string (ADR-0015),
            reusable verbatim as a services-layer ProblemDetail `error_code`.
        context: structured, log-safe data describing the violation — callers
            building an audit event or a 4xx response read this dict rather than
            parsing the message.
    """

    error_code: str = "saena.measurement.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class TenantIsolationError(MeasurementError):
    """A caller supplied a `tenant_id` that does not own the record it passed.

    Raised when a record's OWN embedded `tenant_id` disagrees with the
    caller-supplied leading `tenant_id` (a "forged tenant id" write) — rejected
    before any key is written under either tenant. A cross-tenant READ is NOT
    this error: it is a non-leaking `NotFoundError`, since a lookup keyed by the
    caller's own tenant simply cannot observe another tenant's key existing (see
    `ports.py` module docstring "Tenant isolation").
    """

    error_code = "saena.measurement.tenant_isolation_violation"


class NotFoundError(MeasurementError):
    """No record exists for the given key within the caller's own tenant.

    Also the (non-leaking) result of asking for a key that exists ONLY under a
    different tenant — the caller cannot distinguish "never existed" from
    "exists for someone else", by design.
    """

    error_code = "saena.measurement.not_found"


class IdempotencyConflictError(MeasurementError):
    """A keyed write presented DIFFERENT content than the key already holds.

    Raised by `ConfirmationStore.put_confirmation` and
    `MeasurementWindowStore.open_window` when the same key already holds
    byte-different content. Fail-closed: the stored content (the FIRST accepted
    content) is never overwritten and no arbitrary winner is chosen — the
    caller must reconcile the divergence explicitly.
    """

    error_code = "saena.measurement.idempotency_conflict"


class AppendOnlyViolationError(MeasurementError):
    """An attempt to overwrite an already-recorded append-only decision.

    Raised by `OutcomeDecisionStore.append_decision` when a decision already
    exists for the key with byte-DIFFERENT content. An identical replay is a
    no-op (not this error); only a differing overwrite violates the append-only
    contract.
    """

    error_code = "saena.measurement.append_only_violation"


class EvidenceHashMismatchError(MeasurementError):
    """A content-addressed `put` presented DIFFERENT content for an existing hash.

    Raised by `EvidenceBundleStore.put` when the same `manifest_hash` already
    resolves to byte-different content — a hash collision / integrity violation.
    The content address must be stable: a given `manifest_hash` resolves to
    exactly one content, forever, so this fails closed rather than overwriting.
    """

    error_code = "saena.measurement.evidence_hash_mismatch"


__all__ = [
    "AppendOnlyViolationError",
    "EvidenceHashMismatchError",
    "IdempotencyConflictError",
    "MeasurementError",
    "NotFoundError",
    "TenantIsolationError",
]

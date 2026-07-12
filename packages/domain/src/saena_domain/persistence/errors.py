"""Exception hierarchy for `saena_domain.persistence`.

Follows the same shape as `saena_domain.identity.errors`
(`saena.<category>.<reason>` `error_code` + structured, log-safe `context`
dict) so a services-layer problem-detail mapper can reuse these verbatim —
see `saena_domain/identity/errors.py` module docstring for the rationale.
"""

from __future__ import annotations

from typing import Any


class PersistenceError(Exception):
    """Base class for every error raised by `saena_domain.persistence`.

    Attributes:
        error_code: `saena.<category>.<reason>` taxonomy string (ADR-0015),
            reusable verbatim as a services-layer ProblemDetail `error_code`.
        context: structured, log-safe data describing the violation. Callers
            building an audit event or a 4xx response read this dict rather
            than parsing the exception message.
    """

    error_code: str = "saena.persistence.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class TenantIsolationError(PersistenceError):
    """A caller attempted to read/write another tenant's record.

    ADR-0014 tenant discriminator + data-ownership.md Constraints ("Tenant
    identifiers on core records") — every tenant-scoped port method takes
    `tenant_id` as its first argument and every adapter MUST verify the
    record it is about to return/mutate actually belongs to that tenant
    before doing so. This is the single error raised on that verification
    failing, across every port in this module (never a bare `KeyError` or a
    silent empty result — a cross-tenant access attempt is a security event,
    not a "not found").
    """

    error_code = "saena.persistence.tenant_isolation_violation"


class NotFoundError(PersistenceError):
    """No record exists for the given key (within the caller's own tenant)."""

    error_code = "saena.persistence.not_found"


class DuplicateManifestError(PersistenceError):
    """`ArtifactManifestPort.put` was called twice for the same key with
    DIFFERENT content.

    contract-catalog.md PatchArtifact idempotency key =
    `patch_unit_id+worktree_commit`; the manifest store is put-once per key —
    a second put with the SAME content is an idempotent no-op (replay-safe),
    but a second put with DIFFERENT content under the same key is a real
    conflict (immutability violation) and must fail closed rather than
    silently overwrite.
    """

    error_code = "saena.persistence.duplicate_manifest"


class OutboxValidationError(PersistenceError):
    """`OutboxPort.record` was given a payload that is not a valid envelope.

    W2A scope note (implementation-waves.md): "이벤트는 transactional
    outbox 기록까지 — bus 배선은 2C." The outbox never accepts a
    structurally invalid envelope — every recorded row must already satisfy
    `saena_domain.events`'s dual (jsonschema + pydantic) validation, so a
    downstream W2C bus publisher never has to re-validate before publish.
    """

    error_code = "saena.persistence.outbox_validation_failed"


class LedgerIntegrityError(PersistenceError):
    """The audit ledger's hash chain failed to verify.

    Raised by `AuditLedgerPort.verify()` implementations when
    `saena_domain.audit.verify_chain` reports a broken link — never raised by
    `append`, which enforces continuity structurally (a call that would
    break the chain is rejected before it is stored, see `append_entry`'s own
    `ValueError` semantics, wrapped here for a persistence-layer-consistent
    exception type).
    """

    error_code = "saena.persistence.ledger_integrity_violation"


class DecisionConflictError(PersistenceError):
    """`DecisionRecordPort.record` was given a decision that conflicts with
    an already-stored decision for the same idempotency key
    (`DecisionRecord.decision_key` = contract_hash + canonicalized
    approver_actor_id) — same key, different `decision` value.
    """

    error_code = "saena.persistence.decision_conflict"


# --- tenant status error story (critic MUST-FIX 4 follow-up) -----------------------
#
# `TenantRepository.get`/`update_status` return the GATED `TenantContext`
# wrapper (`saena_domain.identity.tenant`), whose own `__init__` raises
# `TenantSuspendedError`/`TenantTerminatingError` (from
# `saena_domain.identity.errors`, NOT this module — that module is outside
# this unit's exclusive-write paths and is never edited here) for a
# non-`active` stored record. This module deliberately does NOT wrap, shadow,
# or re-export those identity-layer exceptions under a `saena_domain.
# persistence`-prefixed name: doing so would either (a) require catching and
# re-raising them, silently changing their type across the `get`/
# `update_status` boundary and breaking any caller that already handles
# `saena_domain.identity`'s own error hierarchy, or (b) require this module
# importing/subclassing an `identity` error to preserve `isinstance` — itself
# a needless coupling for two exception classes this module raises unchanged.
# Callers should catch `saena_domain.identity.errors.
# {TenantSuspendedError,TenantTerminatingError}` around `TenantRepository.
# get`/`update_status` calls exactly as they would around
# `TenantContext.from_payload` directly — the persistence layer changes
# nothing about that contract, it only adds storage. `TenantRepository.
# get_record` (gate-free, ADR-0014 first-class-status view) never raises
# either error — see its own docstring in `ports.py`.

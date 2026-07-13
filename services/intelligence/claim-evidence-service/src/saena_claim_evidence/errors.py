"""Exception hierarchy for `saena_claim_evidence`.

Follows the same shape as `saena_site_discovery.errors` /
`saena_domain.execution.errors`: every exception carries a stable
`error_code` (`saena.<category>.<reason>`, ADR-0015 taxonomy) and a
structured, log-safe `.context` dict — never raw `claim_text`/`excerpt`
content (CLAUDE.md "증거 없는 완료 선언 금지" applies at the *data*
level too: an error must name the offending identifier, never echo
customer-proprietary claim/evidence text back into a log line).
"""

from __future__ import annotations

from typing import Any


class ClaimEvidenceError(Exception):
    """Base class for every error raised by `saena_claim_evidence`."""

    error_code: str = "saena.internal.claim_evidence_error"
    retryable: bool = False

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), **self.context}


class DuplicateClaimIdError(ClaimEvidenceError):
    """A caller attempted to append a claim under a `claim_id` that already
    exists in this ledger with DIFFERENT content (append-only: a
    byte-identical re-append is a safe idempotent no-op, handled without
    raising — see `ledger.append_claim`)."""

    error_code = "saena.conflict.duplicate_claim_id"


class DuplicateEvidenceIdError(ClaimEvidenceError):
    """A caller attempted to append evidence under an `evidence_id` that
    already exists in this ledger with DIFFERENT content."""

    error_code = "saena.conflict.duplicate_evidence_id"


class ClaimNotFoundError(ClaimEvidenceError):
    """No stored `ExtractedClaim` exists for the requested `(tenant_id,
    project_id, claim_id)` key."""

    error_code = "saena.not_found.claim"


class EvidenceClaimMismatchError(ClaimEvidenceError):
    """An `EvidenceRecord.claim_id` does not reference any claim already
    present in this ledger (evidence must always link to a known claim —
    fail-closed: unlinkable evidence is never silently accepted)."""

    error_code = "saena.validation.evidence_claim_mismatch"


class UnknownEvidenceLinkError(ClaimEvidenceError):
    """A caller attempted to set the link status of an `evidence_id` this
    ledger has no record of."""

    error_code = "saena.not_found.evidence_link"


class CrossTenantLedgerAccessError(ClaimEvidenceError):
    """A caller attempted to store or read a ledger entry under a
    `tenant_id` different from the one it was recorded under — fail closed
    (mirrors `saena_site_discovery.errors.CrossTenantObservationError` /
    `saena_artifact_registry.blobstore`'s cross-tenant gating discipline).
    Default-DENY: an absent or mismatched tenant scope is always rejected,
    never silently widened."""

    error_code = "saena.auth.cross_tenant_denied"


class LedgerIntegrityError(ClaimEvidenceError):
    """The append-only hash chain failed verification (`verify_ledger_chain`
    found a broken link or a recomputed-hash mismatch)."""

    error_code = "saena.integrity.ledger_chain_broken"


__all__ = [
    "ClaimEvidenceError",
    "ClaimNotFoundError",
    "CrossTenantLedgerAccessError",
    "DuplicateClaimIdError",
    "DuplicateEvidenceIdError",
    "EvidenceClaimMismatchError",
    "LedgerIntegrityError",
    "UnknownEvidenceLinkError",
]

"""`InMemoryClaimEvidenceStore` — tenant-scoped, in-memory ledger store.

Mirrors `saena_site_discovery.store.InMemorySiteInventoryStore`'s
tenant-gate discipline exactly: every read/write method takes an explicit
`tenant_id` argument which MUST match the stored/storing record's own
`tenant_id`, and a mismatch on EITHER path raises
`CrossTenantLedgerAccessError` rather than a bare "not found" that would
let a caller distinguish "wrong tenant" from "never existed" — default-DENY
cross-tenant access (task hard constraint: "tenant_id discriminator
mandatory; cross-tenant default-DENY").

This is a reference in-memory adapter for this unit's own tests only — a
real persistence adapter (SQL, following `saena_domain.persistence`'s port
shape) is out of this patch unit's scope, same carve-out
`saena_site_discovery.store`'s module docstring records for itself.

Ledger state (`ClaimEvidenceLedgerState`) and `EvidenceLinkStatus` tracking
are both stored per `(tenant_id, project_id)` — a project's ledger and
link-status map are always mutated together, atomically, under one lock.
"""

from __future__ import annotations

import threading
from datetime import datetime

from saena_schemas.domain.evidence_record_v1 import EvidenceRecord
from saena_schemas.domain.extracted_claim_v1 import ExtractedClaim

from saena_claim_evidence.errors import ClaimNotFoundError, CrossTenantLedgerAccessError
from saena_claim_evidence.evaluation import (
    ClaimPublishability,
    EvidenceFreshnessPolicy,
    EvidenceLinkStatus,
)
from saena_claim_evidence.ledger import (
    DEFAULT_FRESHNESS_POLICY,
    ClaimEvidenceLedgerEntry,
    ClaimEvidenceLedgerState,
    append_claim,
    append_evidence,
    set_evidence_link_status,
)

_LedgerKey = tuple[str, str]  # (tenant_id, project_id)


class InMemoryClaimEvidenceStore:
    """Pure-Python, tenant-scoped claim/evidence ledger store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ledgers: dict[_LedgerKey, ClaimEvidenceLedgerState] = {}
        self._link_statuses: dict[_LedgerKey, dict[str, EvidenceLinkStatus]] = {}

    def _guard_tenant(self, tenant_id: str, record_tenant_id: str) -> None:
        if tenant_id != record_tenant_id:
            raise CrossTenantLedgerAccessError(
                "record tenant_id does not match the requesting tenant_id",
                context={"requested_tenant_id": tenant_id},
            )

    def append_claim(self, tenant_id: str, claim: ExtractedClaim) -> ClaimEvidenceLedgerEntry:
        """Append `claim` under `(tenant_id, claim.project_id)`.

        Raises `CrossTenantLedgerAccessError` if `claim.tenant_id != tenant_id`.
        """
        self._guard_tenant(tenant_id, claim.tenant_id.root)
        key = (tenant_id, claim.project_id.root)
        with self._lock:
            ledger_state = self._ledgers.get(key, ())
            new_state, entry = append_claim(ledger_state, claim)
            self._ledgers[key] = new_state
            self._link_statuses.setdefault(key, {})
        return entry

    def append_evidence(
        self,
        tenant_id: str,
        evidence: EvidenceRecord,
        *,
        now: datetime,
        policy: EvidenceFreshnessPolicy = DEFAULT_FRESHNESS_POLICY,
    ) -> ClaimEvidenceLedgerEntry:
        """Append `evidence` under `(tenant_id, evidence.project_id)`.

        Raises `CrossTenantLedgerAccessError` if `evidence.tenant_id !=
        tenant_id`; `EvidenceClaimMismatchError` (propagated from
        `ledger.append_evidence`) if `evidence.claim_id` is not already
        registered under this same `(tenant_id, project_id)` ledger.
        """
        self._guard_tenant(tenant_id, evidence.tenant_id.root)
        key = (tenant_id, evidence.project_id.root)
        with self._lock:
            ledger_state = self._ledgers.get(key, ())
            link_statuses = self._link_statuses.setdefault(key, {})
            new_state, entry = append_evidence(
                ledger_state, evidence, link_statuses=link_statuses, policy=policy, now=now
            )
            self._ledgers[key] = new_state
        return entry

    def set_evidence_link_status(
        self,
        tenant_id: str,
        project_id: str,
        *,
        evidence_id: str,
        status: EvidenceLinkStatus,
        now: datetime,
        policy: EvidenceFreshnessPolicy = DEFAULT_FRESHNESS_POLICY,
    ) -> ClaimEvidenceLedgerState:
        """Set `evidence_id`'s link status within `(tenant_id, project_id)`'s
        ledger and re-evaluate the owning claim's publishability.

        Tenant scoping here is structural (the ledger is looked up strictly
        by the caller-supplied `(tenant_id, project_id)` key — there is no
        separate record to cross-check `tenant_id` against, unlike
        `append_claim`/`append_evidence`, which validate the *payload's own*
        `tenant_id` field). An unknown `(tenant_id, project_id)` pair simply
        has an empty ledger, so `set_evidence_link_status` raises
        `UnknownEvidenceLinkError` (propagated from `ledger.
        set_evidence_link_status`) the same way it would for any other
        never-appended `evidence_id`.
        """
        key = (tenant_id, project_id)
        with self._lock:
            ledger_state = self._ledgers.get(key, ())
            link_statuses = self._link_statuses.setdefault(key, {})
            new_state = set_evidence_link_status(
                ledger_state,
                evidence_id=evidence_id,
                status=status,
                link_statuses=link_statuses,
                policy=policy,
                now=now,
            )
            self._ledgers[key] = new_state
        return new_state

    def get_ledger(self, tenant_id: str, project_id: str) -> ClaimEvidenceLedgerState:
        """Return the full append-only ledger for `(tenant_id, project_id)`
        (empty tuple if nothing has been appended yet — never raises for an
        unknown project, matching `tuple()`'s natural "nothing here" empty
        state; this deliberately differs from `get_claim_publishability`,
        which DOES raise for an unknown `claim_id` since a claim lookup has
        a specific identifier a caller could have gotten wrong)."""
        with self._lock:
            return self._ledgers.get((tenant_id, project_id), ())

    def get_claim_publishability(
        self, tenant_id: str, project_id: str, claim_id: str
    ) -> ClaimPublishability:
        """Return the current (latest-entry) `ClaimPublishability` for
        `claim_id` within `(tenant_id, project_id)`.

        Raises `ClaimNotFoundError` if `claim_id` has never been appended
        under this exact `(tenant_id, project_id)` key — a claim appended
        under a DIFFERENT tenant/project is indistinguishable from "never
        appended" to this caller, by design (never leak cross-tenant
        existence, mirrors `saena_site_discovery.store`'s `get` discipline).
        """
        with self._lock:
            ledger_state = self._ledgers.get((tenant_id, project_id), ())
        for entry in reversed(ledger_state):
            if (
                entry.kind == "claim"
                and entry.claim is not None
                and entry.claim.claim_id == claim_id
            ):
                assert entry.publishability is not None
                return entry.publishability
        raise ClaimNotFoundError(
            f"claim_id {claim_id!r} not found for this tenant/project",
            context={"claim_id": claim_id},
        )


__all__ = ["InMemoryClaimEvidenceStore"]

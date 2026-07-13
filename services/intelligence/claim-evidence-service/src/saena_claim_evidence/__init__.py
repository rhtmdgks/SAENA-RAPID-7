"""saena_claim_evidence — atomic claim + evidence ledger (write-model / command
side), w4-04.

Scope (exclusive paths, this patch unit ONLY):
    services/intelligence/claim-evidence-service/** (this package),
    tests/unit/svc_claim_evidence/**

Explicitly OUT of scope for this unit (a SEPARATE patch unit, w4-11 — task
instruction: "Do NOT build QEEG"): the Question-Entity-Evidence Graph
read-only projection/replay module. Nothing in this package builds a graph
projection, a replay mechanism, or any read-model over the ledger below —
this package is the command/write side only (append claims, append
evidence, evaluate publishability, emit a version-notification event).

Also explicitly OUT of scope (CLAUDE.md Engine scope v1 / wave4-plan.md
"Forbidden in W4"): no Google/Gemini engine support, no outcome/DiD/causal/
lift computation, no absorption-analysis, no strategy-card. This package
never computes or stores an observed effect, delta, or significance value.

Core design, one paragraph: an `ExtractedClaim` (generated
`saena_schemas.domain.extracted_claim_v1.ExtractedClaim`) is publishable
only if `evaluate_claim_publishability` finds at least one linked
`EvidenceRecord` (generated `saena_schemas.domain.evidence_record_v1.
EvidenceRecord`) that is present, fresh (per an injectable
`EvidenceFreshnessPolicy`, evaluated against an injectable "now" — no
wall-clock reads anywhere in this package), and not administratively
blocked (`EvidenceLinkStatus.BLOCKED`, a domain-only annotation this
package adds on top of the generated schema, which itself has no
blocked/unblocked field). Absent, stale, or blocked evidence => the
returned `ClaimPublishability.publishable` is `False` and
`blocking_reasons` is populated. `append_claim`/`append_evidence`/
`set_evidence_link_status` all re-evaluate `evaluate_claim_publishability`
on every mutation that could affect a claim and record the outcome as a
fresh, appended `ClaimEvidenceLedgerEntry.publishability` value (the
claim's own generated `status` field, `active`/`superseded`/`retracted`,
is never silently rewritten by this evaluation — publishability is a
ledger-derived fact this package tracks alongside the claim, not a
mutation of the claim record's own schema-level lifecycle state) — the
core requirement ("a claim is publishable ONLY if ...", "no valid
evidence -> not publishable") is therefore enforced as a stored,
re-checked fact on every ledger mutation, not merely a value a caller
might forget to call (see `ledger.py`'s "fail-closed-on-mutation" section
for the exact append-only mechanics).

Hashing: `content_hash` (both the `EvidenceRecord.content_hash` field and
this package's own ledger-entry `content_hash`) is produced by
`saena_domain.audit.canonical.canonical_json` + `sha256_hex` — the SAME
canonicalization the audit hash-chain and the w4-09 experiment ledger
build on (`hashing.py` re-exports rather than reimplements). No second
hashing rule is invented anywhere in this package.

Public API:
    EvidenceFreshnessPolicy / DEFAULT_FRESHNESS_POLICY
    EvidenceLinkStatus
    ClaimPublishability / evaluate_claim_publishability
    compute_evidence_content_hash / compute_ledger_entry_hash
    ClaimEvidenceLedgerEntry / ClaimEvidenceLedgerState
    append_claim / append_evidence / set_evidence_link_status
    verify_ledger_chain / raise_if_broken
    InMemoryClaimEvidenceStore
    build_claim_evidence_versioned_event
    ClaimEvidenceError and every specific error subclass
"""

from __future__ import annotations

from saena_claim_evidence.errors import (
    ClaimEvidenceError,
    ClaimNotFoundError,
    CrossTenantLedgerAccessError,
    DuplicateClaimIdError,
    DuplicateEvidenceIdError,
    EvidenceClaimMismatchError,
    LedgerIntegrityError,
    UnknownEvidenceLinkError,
)
from saena_claim_evidence.evaluation import (
    ClaimPublishability,
    EvidenceFreshnessPolicy,
    evaluate_claim_publishability,
)
from saena_claim_evidence.events import build_claim_evidence_versioned_event
from saena_claim_evidence.hashing import (
    compute_evidence_content_hash,
    compute_ledger_entry_hash,
)
from saena_claim_evidence.ledger import (
    DEFAULT_FRESHNESS_POLICY,
    ClaimEvidenceLedgerEntry,
    ClaimEvidenceLedgerState,
    EvidenceLinkStatus,
    append_claim,
    append_evidence,
    set_evidence_link_status,
    verify_ledger_chain,
)
from saena_claim_evidence.store import InMemoryClaimEvidenceStore

__all__ = [
    "DEFAULT_FRESHNESS_POLICY",
    "ClaimEvidenceError",
    "ClaimEvidenceLedgerEntry",
    "ClaimEvidenceLedgerState",
    "ClaimNotFoundError",
    "ClaimPublishability",
    "CrossTenantLedgerAccessError",
    "DuplicateClaimIdError",
    "DuplicateEvidenceIdError",
    "EvidenceClaimMismatchError",
    "EvidenceFreshnessPolicy",
    "EvidenceLinkStatus",
    "InMemoryClaimEvidenceStore",
    "LedgerIntegrityError",
    "UnknownEvidenceLinkError",
    "append_claim",
    "append_evidence",
    "build_claim_evidence_versioned_event",
    "compute_evidence_content_hash",
    "compute_ledger_entry_hash",
    "evaluate_claim_publishability",
    "set_evidence_link_status",
    "verify_ledger_chain",
]

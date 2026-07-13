"""Append-only claim + evidence ledger — the write-model core (w4-04).

Mirrors `saena_domain.experiment.ledger`'s append-only hash-chain shape
(own-hash + `previous_hash` chain-anchor, `verify_ledger_chain` doing the
same two-part own-hash-recompute + prev-linkage check as
`saena_domain.experiment.ledger.verify_ledger` /
`saena_domain.audit.chain.verify_chain`) applied to TWO record kinds
(`ExtractedClaim` and `EvidenceRecord`) sharing one chain, rather than one.

Fail-closed-on-mutation (the module docstring in `__init__.py` names this):
`append_claim`, `append_evidence`, and `set_evidence_link_status` all
re-evaluate `evaluate_claim_publishability` for every claim their append
could affect and store the outcome as `ClaimEvidenceLedgerEntry.
publishability` on the CLAIM entry's most recent occurrence in the ledger
tuple — the ledger is still strictly append-only (nothing is ever deleted
or edited in place), but a claim's "current" publishability is always the
`publishability` value carried by its LAST entry in ledger order, giving
`append_evidence`/`set_evidence_link_status` a way to record a
publishability change without violating append-only-ness (a fresh
`ClaimEntry` "republish" record is appended, carrying the same
`claim.status` as before it — this ledger never silently mutates
`ExtractedClaim.status` itself, only ever appends a fresh, re-evaluated
entry, exactly like `saena_domain.experiment.ledger.register`'s "no-op
replay never mutates in place, always appends or returns the existing
entry" discipline).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from saena_schemas.domain.evidence_record_v1 import EvidenceRecord
from saena_schemas.domain.extracted_claim_v1 import ExtractedClaim

from saena_claim_evidence.errors import (
    ClaimNotFoundError,
    DuplicateClaimIdError,
    DuplicateEvidenceIdError,
    EvidenceClaimMismatchError,
    LedgerIntegrityError,
    UnknownEvidenceLinkError,
)
from saena_claim_evidence.evaluation import (
    ClaimPublishability,
    EvidenceFreshnessPolicy,
    EvidenceLinkStatus,
    evaluate_claim_publishability,
)
from saena_claim_evidence.hashing import compute_ledger_entry_hash

#: This package does not itself fix a numeric freshness bound (OPEN
#: decision — see `evaluation.py` module docstring); this constant exists
#: ONLY so `append_claim`/`append_evidence` have a usable, explicit,
#: clearly-not-hidden default a caller may override per call — it is not a
#: normative production value.
DEFAULT_FRESHNESS_POLICY = EvidenceFreshnessPolicy(max_age_seconds=90 * 24 * 3600)

GENESIS: None = None


@dataclass(frozen=True, slots=True)
class ClaimEvidenceLedgerEntry:
    """One append-only ledger entry — either a claim entry or an evidence
    entry, discriminated by `kind`. Exactly one of `claim`/`evidence` is
    non-`None`, matching its `kind`. `publishability` is populated ONLY on
    claim-kind entries (see module docstring "fail-closed-on-mutation").
    """

    kind: str  # "claim" | "evidence"
    tenant_id: str
    project_id: str
    claim: ExtractedClaim | None
    evidence: EvidenceRecord | None
    publishability: ClaimPublishability | None
    canonical_hash: str
    previous_hash: str | None

    def __post_init__(self) -> None:
        if self.kind not in ("claim", "evidence"):
            msg = f"kind must be 'claim' or 'evidence', got {self.kind!r}"
            raise ValueError(msg)
        if self.kind == "claim" and self.claim is None:
            msg = "a 'claim' entry must carry a non-None claim"
            raise ValueError(msg)
        if self.kind == "evidence" and self.evidence is None:
            msg = "an 'evidence' entry must carry a non-None evidence"
            raise ValueError(msg)


#: Ledger state is an immutable tuple of entries in append order — mirrors
#: `saena_domain.experiment.ledger.LedgerState`'s "returns a NEW tuple"
#: contract; nothing here ever mutates an existing tuple in place.
ClaimEvidenceLedgerState = tuple[ClaimEvidenceLedgerEntry, ...]


def _claim_material(claim: ExtractedClaim) -> dict[str, Any]:
    return {
        "kind": "claim",
        "tenant_id": claim.tenant_id.root,
        "project_id": claim.project_id.root,
        "claim_id": claim.claim_id,
        "entity_id": claim.entity_id,
        "claim_text": claim.claim_text,
        "status": claim.status.value,
        "effective_from": claim.effective_from.root,
        "created_at": claim.created_at.root,
    }


def _evidence_material(evidence: EvidenceRecord) -> dict[str, Any]:
    return {
        "kind": "evidence",
        "tenant_id": evidence.tenant_id.root,
        "project_id": evidence.project_id.root,
        "evidence_id": evidence.evidence_id,
        "claim_id": evidence.claim_id,
        "source_uri": evidence.source_uri.root,
        "excerpt": evidence.excerpt,
        "freshness_checked_at": evidence.freshness_checked_at.root,
        "content_hash": evidence.content_hash.root,
    }


def _latest_claims(ledger_state: ClaimEvidenceLedgerState) -> dict[str, ClaimEvidenceLedgerEntry]:
    """The most recent ledger entry per `claim_id`, in first-seen-order of
    that claim_id's LAST occurrence (dict insertion order over a linear
    scan — later occurrences overwrite earlier ones, so the final dict
    value for a given key is always that claim's newest entry)."""
    latest: dict[str, ClaimEvidenceLedgerEntry] = {}
    for entry in ledger_state:
        if entry.kind == "claim" and entry.claim is not None:
            latest[entry.claim.claim_id] = entry
    return latest


def _all_evidence_for_claim(
    ledger_state: ClaimEvidenceLedgerState, claim_id: str
) -> tuple[EvidenceRecord, ...]:
    """Every distinct `evidence_id` linked to `claim_id`, using each
    evidence_id's LATEST appended record (an evidence_id may only ever be
    appended once per this ledger's duplicate-content rule, so "latest" and
    "only" coincide in practice, but the lookup is still latest-wins for
    consistency with `_latest_claims`)."""
    latest_by_id: dict[str, EvidenceRecord] = {}
    for entry in ledger_state:
        if (
            entry.kind == "evidence"
            and entry.evidence is not None
            and entry.evidence.claim_id == claim_id
        ):
            latest_by_id[entry.evidence.evidence_id] = entry.evidence
    return tuple(latest_by_id.values())


def _reevaluate(
    ledger_state: ClaimEvidenceLedgerState,
    *,
    claim_id: str,
    link_statuses: dict[str, EvidenceLinkStatus],
    policy: EvidenceFreshnessPolicy,
    now: datetime,
) -> ClaimEvidenceLedgerState:
    """Append a fresh claim entry re-stating the claim's current content
    with an updated `publishability`, IF the recomputed publishability
    differs from the claim's current latest entry (no-op — no new entry —
    when nothing changed, keeping replay/idempotent calls cheap and the
    ledger free of no-op noise)."""
    latest_claims = _latest_claims(ledger_state)
    current = latest_claims.get(claim_id)
    if current is None or current.claim is None:
        raise ClaimNotFoundError(
            f"claim_id {claim_id!r} not found in this ledger", context={"claim_id": claim_id}
        )

    evidence_records = _all_evidence_for_claim(ledger_state, claim_id)
    publishability = evaluate_claim_publishability(
        claim_id=claim_id,
        evidence_records=evidence_records,
        link_statuses=link_statuses,
        policy=policy,
        now=now,
    )
    if current.publishability == publishability:
        return ledger_state

    previous_hash = ledger_state[-1].canonical_hash if ledger_state else GENESIS
    material = _claim_material(current.claim)
    canonical_hash = compute_ledger_entry_hash(material)
    entry = ClaimEvidenceLedgerEntry(
        kind="claim",
        tenant_id=current.tenant_id,
        project_id=current.project_id,
        claim=current.claim,
        evidence=None,
        publishability=publishability,
        canonical_hash=canonical_hash,
        previous_hash=previous_hash,
    )
    return (*ledger_state, entry)


def append_claim(
    ledger_state: ClaimEvidenceLedgerState,
    claim: ExtractedClaim,
) -> tuple[ClaimEvidenceLedgerState, ClaimEvidenceLedgerEntry]:
    """Append `claim` to `ledger_state`. Returns `(new_ledger_state, stored_entry)`.

    Append-only, fail-closed idempotency (mirrors
    `saena_domain.experiment.ledger.register`):
      - new `claim_id`: appended with `publishability` evaluated against
        ZERO linked evidence (unsupported by definition — case (a) of the
        fail-closed rule: "present" fails trivially with no evidence yet).
      - existing `claim_id`, byte-identical content: no-op replay, returns
        the unchanged ledger and the already-stored latest entry.
      - existing `claim_id`, different content: `DuplicateClaimIdError`
        (this ledger has no claim-content-versioning story beyond
        `ExtractedClaim.status`/`effective_from` — a genuine claim revision
        is a NEW `claim_id`, not a same-id content change).
    """
    latest_claims = _latest_claims(ledger_state)
    existing = latest_claims.get(claim.claim_id)
    if existing is not None and existing.claim is not None:
        if _claim_material(existing.claim) == _claim_material(claim):
            return ledger_state, existing
        raise DuplicateClaimIdError(
            f"claim_id {claim.claim_id!r} already exists with different content",
            context={"claim_id": claim.claim_id},
        )

    previous_hash = ledger_state[-1].canonical_hash if ledger_state else GENESIS
    material = _claim_material(claim)
    canonical_hash = compute_ledger_entry_hash(material)
    publishability = evaluate_claim_publishability(
        claim_id=claim.claim_id,
        evidence_records=(),
        link_statuses={},
        policy=DEFAULT_FRESHNESS_POLICY,
        now=_parse_effective_from(claim),
    )
    entry = ClaimEvidenceLedgerEntry(
        kind="claim",
        tenant_id=claim.tenant_id.root,
        project_id=claim.project_id.root,
        claim=claim,
        evidence=None,
        publishability=publishability,
        canonical_hash=canonical_hash,
        previous_hash=previous_hash,
    )
    return (*ledger_state, entry), entry


def _parse_effective_from(claim: ExtractedClaim) -> datetime:
    return datetime.fromisoformat(claim.effective_from.root.replace("Z", "+00:00"))


def append_evidence(
    ledger_state: ClaimEvidenceLedgerState,
    evidence: EvidenceRecord,
    *,
    link_statuses: dict[str, EvidenceLinkStatus],
    policy: EvidenceFreshnessPolicy = DEFAULT_FRESHNESS_POLICY,
    now: datetime,
) -> tuple[ClaimEvidenceLedgerState, ClaimEvidenceLedgerEntry]:
    """Append `evidence` to `ledger_state`, then re-evaluate and (if
    changed) append a fresh publishability-updated entry for
    `evidence.claim_id`.

    Fail-closed:
      - `evidence.claim_id` must already exist in this ledger
        (`EvidenceClaimMismatchError` otherwise — evidence can never link
        to an unknown claim).
      - new `evidence_id`: appended, `link_statuses` gains a `LINKED`
        default entry (mutated in place — `link_statuses` is caller-owned
        mutable state threaded through by `store.py`, matching this
        module's "link-status tracking lives outside the immutable ledger
        tuple" design).
      - existing `evidence_id`, byte-identical content: no-op replay.
      - existing `evidence_id`, different content: `DuplicateEvidenceIdError`.

    Returns `(new_ledger_state, stored_evidence_entry)` — the evidence
    entry only; the caller can inspect `new_ledger_state[-1]` for the
    trailing re-evaluated claim entry when one was appended.
    """
    latest_claims = _latest_claims(ledger_state)
    if evidence.claim_id not in latest_claims:
        raise EvidenceClaimMismatchError(
            f"evidence.claim_id {evidence.claim_id!r} does not reference any "
            "claim already present in this ledger",
            context={"claim_id": evidence.claim_id, "evidence_id": evidence.evidence_id},
        )

    existing_evidence = next(
        (
            e.evidence
            for e in reversed(ledger_state)
            if e.kind == "evidence"
            and e.evidence is not None
            and e.evidence.evidence_id == evidence.evidence_id
        ),
        None,
    )
    if existing_evidence is not None:
        if _evidence_material(existing_evidence) == _evidence_material(evidence):
            existing_entry = next(
                e
                for e in reversed(ledger_state)
                if e.kind == "evidence"
                and e.evidence is not None
                and e.evidence.evidence_id == evidence.evidence_id
            )
            return ledger_state, existing_entry
        raise DuplicateEvidenceIdError(
            f"evidence_id {evidence.evidence_id!r} already exists with different content",
            context={"evidence_id": evidence.evidence_id},
        )

    previous_hash = ledger_state[-1].canonical_hash if ledger_state else GENESIS
    material = _evidence_material(evidence)
    canonical_hash = compute_ledger_entry_hash(material)
    entry = ClaimEvidenceLedgerEntry(
        kind="evidence",
        tenant_id=evidence.tenant_id.root,
        project_id=evidence.project_id.root,
        claim=None,
        evidence=evidence,
        publishability=None,
        canonical_hash=canonical_hash,
        previous_hash=previous_hash,
    )
    new_state: ClaimEvidenceLedgerState = (*ledger_state, entry)
    link_statuses.setdefault(evidence.evidence_id, EvidenceLinkStatus.LINKED)

    new_state = _reevaluate(
        new_state,
        claim_id=evidence.claim_id,
        link_statuses=link_statuses,
        policy=policy,
        now=now,
    )
    return new_state, entry


def set_evidence_link_status(
    ledger_state: ClaimEvidenceLedgerState,
    *,
    evidence_id: str,
    status: EvidenceLinkStatus,
    link_statuses: dict[str, EvidenceLinkStatus],
    policy: EvidenceFreshnessPolicy = DEFAULT_FRESHNESS_POLICY,
    now: datetime,
) -> ClaimEvidenceLedgerState:
    """Set `evidence_id`'s link status (e.g. administratively `BLOCKED`)
    and re-evaluate the owning claim's publishability.

    `UnknownEvidenceLinkError` if `evidence_id` was never appended to this
    ledger — a caller cannot set the status of evidence that does not
    exist (fail-closed: no implicit creation).
    """
    owning_claim_id = next(
        (
            e.evidence.claim_id
            for e in ledger_state
            if e.kind == "evidence"
            and e.evidence is not None
            and e.evidence.evidence_id == evidence_id
        ),
        None,
    )
    if owning_claim_id is None:
        raise UnknownEvidenceLinkError(
            f"evidence_id {evidence_id!r} is not known to this ledger",
            context={"evidence_id": evidence_id},
        )

    link_statuses[evidence_id] = status
    return _reevaluate(
        ledger_state,
        claim_id=owning_claim_id,
        link_statuses=link_statuses,
        policy=policy,
        now=now,
    )


def verify_ledger_chain(ledger_state: ClaimEvidenceLedgerState) -> tuple[bool, int | None]:
    """Verify every entry's `canonical_hash` and the `previous_hash` chain.

    Returns `(True, None)` if intact, or `(False, i)` where `i` is the
    index of the FIRST entry that fails verification — mirrors
    `saena_domain.experiment.ledger.verify_ledger`'s two-part check
    exactly (own-hash recompute + prev-linkage check).
    """
    expected_prev: str | None = GENESIS
    for index, entry in enumerate(ledger_state):
        if entry.previous_hash != expected_prev:
            return False, index
        if entry.kind == "claim" and entry.claim is not None:
            material = _claim_material(entry.claim)
        elif entry.kind == "evidence" and entry.evidence is not None:
            material = _evidence_material(entry.evidence)
        else:  # pragma: no cover - unreachable, __post_init__ enforces kind/payload pairing
            return False, index
        recomputed = compute_ledger_entry_hash(material)
        if recomputed != entry.canonical_hash:
            return False, index
        expected_prev = entry.canonical_hash
    return True, None


def raise_if_broken(ledger_state: ClaimEvidenceLedgerState) -> None:
    """Convenience wrapper: raises `LedgerIntegrityError` if
    `verify_ledger_chain` finds a break, otherwise returns `None`."""
    ok, index = verify_ledger_chain(ledger_state)
    if not ok:
        raise LedgerIntegrityError(
            f"ledger chain verification failed at entry index {index}",
            context={"broken_index": index},
        )


__all__ = [
    "DEFAULT_FRESHNESS_POLICY",
    "GENESIS",
    "ClaimEvidenceLedgerEntry",
    "ClaimEvidenceLedgerState",
    "EvidenceLinkStatus",
    "append_claim",
    "append_evidence",
    "raise_if_broken",
    "set_evidence_link_status",
    "verify_ledger_chain",
]

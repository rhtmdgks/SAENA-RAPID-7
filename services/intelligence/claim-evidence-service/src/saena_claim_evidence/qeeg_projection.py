"""QEEG (Question–Entity–Evidence Graph) read-only projection over the
claim-evidence ledger (w4-11).

Physical projection owner = claim-evidence-service (ADR-0007;
`docs/architecture/data-ownership.md:29`); this module is that ownership
put into code — the concrete adapter that folds THIS service's
`ClaimEvidenceLedgerState`/`ClaimEvidenceLedgerEntry` write-model records
into `saena_domain.qeeg`'s generic, PII-free `ClaimFact`/`EvidenceFact`
replay engine.

Split from w4-04 (`ledger.py`/`evaluation.py`/`store.py`) deliberately —
see `wave4-plan.md`: "QEEG belongs to claim-evidence but split to w4-11 to
keep w4-04 core deterministic". This module ADDS a projection/read-model
file; it does NOT modify `ledger.py`/`evaluation.py`/`store.py` (this
unit's own exclusive-path constraint) — every function here only READS a
`ClaimEvidenceLedgerState`/`ClaimEvidenceLedgerEntry`/
`InMemoryClaimEvidenceStore`, never appends to or mutates one.

READ-ONLY CQRS (`docs/architecture/data-ownership.md` "Cross-cutting read
model 규칙"): `build_qeeg_projection`/`replay_qeeg_projection_from_store`
never call `append_claim`/`append_evidence`/`set_evidence_link_status` —
mutating the claim/evidence ledger is exclusively the write-model's
command API (`saena_claim_evidence.ledger`/`saena_claim_evidence.store`),
consumed by callers who need to WRITE; this module exists only for
callers who need to READ a claims-by-entity / evidence-by-claim /
publishability-status view.

Determinism / rebuildability (task hard constraint): `build_qeeg_projection`
folds a `ClaimEvidenceLedgerState` tuple (already-ordered, already
append-only) into `saena_domain.qeeg.replay.replay` — the SAME ledger
state, folded any number of times, in any process, always yields a
structurally-`==` `QeegProjectionState` (proven by `saena_domain.qeeg`'s
own determinism guarantee; this module adds no additional non-determinism
— no wall-clock read, no I/O, no randomness anywhere in
`_claim_entry_to_fact`/`_evidence_entry_to_fact`/`build_qeeg_projection`).

Tenant scoping: `build_qeeg_projection` takes an explicit `tenant_id` and
only folds ledger entries whose OWN `tenant_id` matches it — an entry
belonging to a different tenant is never silently absorbed (mirrors
`saena_claim_evidence.store.InMemoryClaimEvidenceStore`'s own
`CrossTenantLedgerAccessError` discipline, but expressed as a filter here
rather than a raise, since a full ledger tuple pulled from
`InMemoryClaimEvidenceStore.get_ledger(tenant_id, project_id)` is already
tenant-scoped by construction — this filter is a defense-in-depth
belt-and-suspenders check, never the primary tenant gate).

No PII: `_claim_entry_to_fact`/`_evidence_entry_to_fact` copy over ONLY
identifiers, `status`/publishability enums, and evidence-id links —
neither `claim.claim_text` nor `evidence.excerpt`/`evidence.source_uri`
is ever read by this module, matching `saena_domain.qeeg.models`'s own
"no field for them to begin with" design.
"""

from __future__ import annotations

from saena_domain.qeeg import (
    ClaimFact,
    EvidenceFact,
    QeegClaimView,
    QeegLinkStatus,
    QeegProjectionState,
    claims_by_entity,
    empty_projection,
    evidence_by_claim,
    publishability_of,
)
from saena_domain.qeeg import (
    apply_claim_fact as _apply_claim_fact,
)
from saena_domain.qeeg import (
    apply_evidence_fact as _apply_evidence_fact,
)

from saena_claim_evidence.evaluation import EvidenceLinkStatus
from saena_claim_evidence.ledger import ClaimEvidenceLedgerEntry, ClaimEvidenceLedgerState
from saena_claim_evidence.store import InMemoryClaimEvidenceStore

_LINK_STATUS_MAP: dict[EvidenceLinkStatus, QeegLinkStatus] = {
    EvidenceLinkStatus.LINKED: QeegLinkStatus.LINKED,
    EvidenceLinkStatus.BLOCKED: QeegLinkStatus.BLOCKED,
}


def _claim_entry_to_fact(entry: ClaimEvidenceLedgerEntry) -> ClaimFact:
    assert entry.claim is not None
    assert entry.publishability is not None
    return ClaimFact(
        tenant_id=entry.tenant_id,
        project_id=entry.project_id,
        claim_id=entry.claim.claim_id,
        entity_id=entry.claim.entity_id,
        status=entry.claim.status.value,
        publishable=entry.publishability.publishable,
        blocking_reasons=entry.publishability.blocking_reasons,
        supporting_evidence_ids=entry.publishability.supporting_evidence_ids,
    )


def _evidence_entry_to_fact(
    entry: ClaimEvidenceLedgerEntry,
    *,
    link_statuses: dict[str, EvidenceLinkStatus],
) -> EvidenceFact:
    assert entry.evidence is not None
    evidence_id = entry.evidence.evidence_id
    link_status = link_statuses.get(evidence_id, EvidenceLinkStatus.BLOCKED)
    return EvidenceFact(
        tenant_id=entry.tenant_id,
        project_id=entry.project_id,
        evidence_id=evidence_id,
        claim_id=entry.evidence.claim_id,
        link_status=_LINK_STATUS_MAP[link_status],
    )


def build_qeeg_projection(
    tenant_id: str,
    ledger_state: ClaimEvidenceLedgerState,
    *,
    link_statuses: dict[str, EvidenceLinkStatus] | None = None,
) -> QeegProjectionState:
    """Build a `QeegProjectionState` for `tenant_id` by replaying
    `ledger_state` from scratch, in ledger order.

    `link_statuses` is optional (defaults to `{}`, matching the ledger's
    own "unregistered evidence_id defaults to BLOCKED" fail-closed rule —
    see `saena_claim_evidence.evaluation.evaluate_claim_publishability`'s
    identical `link_statuses.get(evidence.evidence_id,
    EvidenceLinkStatus.BLOCKED)` default). It exists only so a caller
    holding the write-model's own `link_statuses` map (e.g. pulled
    alongside a ledger from a future real persistence adapter) can pass it
    through for `EvidenceFact.link_status` accuracy; the PROJECTED
    publishability itself is never recomputed from `link_statuses` here —
    it is always copied verbatim from the ledger entry's own
    `publishability` (already fail-closed-evaluated by the write-model
    at append time), never a second, competing computation.

    Entries whose OWN `tenant_id` does not equal `tenant_id` are skipped
    (defense-in-depth tenant filter — see module docstring).
    """
    resolved_link_statuses = link_statuses if link_statuses is not None else {}
    facts: list[ClaimFact | EvidenceFact] = []
    for entry in ledger_state:
        if entry.tenant_id != tenant_id:
            continue
        if entry.kind == "claim":
            facts.append(_claim_entry_to_fact(entry))
        else:
            facts.append(_evidence_entry_to_fact(entry, link_statuses=resolved_link_statuses))

    state = empty_projection(tenant_id)
    for fact in facts:
        if isinstance(fact, ClaimFact):
            state = _apply_claim_fact(state, fact)
        else:
            state = _apply_evidence_fact(state, fact)
    return state


def replay_qeeg_projection_from_store(
    store: InMemoryClaimEvidenceStore,
    *,
    tenant_id: str,
    project_id: str,
) -> QeegProjectionState:
    """Convenience wrapper: pull `(tenant_id, project_id)`'s ledger from
    `store` and build a `QeegProjectionState`.

    READ-ONLY: calls only `store.get_ledger` (a read method) — never
    `store.append_claim`/`store.append_evidence`/
    `store.set_evidence_link_status`. `InMemoryClaimEvidenceStore` has no
    public accessor for its internal `_link_statuses` map (private by
    design — see `store.py`), so this wrapper does not pass one through to
    `build_qeeg_projection`, which then applies the SAME fail-closed
    default `store.py`/`evaluation.py` themselves use
    (`EvidenceLinkStatus.BLOCKED` for an unregistered `evidence_id`) — see
    `build_qeeg_projection`'s own `link_statuses` docstring. This affects
    ONLY the informational `EvidenceFact.link_status` field; the projected
    claim's own `publishable`/`blocking_reasons` are always copied
    verbatim from the ledger entry's own already-fail-closed-evaluated
    `publishability` and are entirely unaffected by this default (see
    `build_qeeg_projection`'s docstring — publishability is never
    recomputed by this module, only replayed).
    """
    ledger_state = store.get_ledger(tenant_id, project_id)
    return build_qeeg_projection(tenant_id, ledger_state)


__all__ = [
    "QeegClaimView",
    "QeegProjectionState",
    "build_qeeg_projection",
    "claims_by_entity",
    "evidence_by_claim",
    "publishability_of",
    "replay_qeeg_projection_from_store",
]

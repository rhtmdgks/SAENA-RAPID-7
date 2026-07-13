"""QEEG replay engine — deterministic, idempotent fold over claim/evidence
facts (w4-11).

Pure/deterministic (task hard constraint): every function here is a pure
fold — no I/O, no wall-clock read, no random/UUID generation, no hidden
global state. The SAME ordered sequence of `ClaimFact`/`EvidenceFact`
values folded via `replay` always yields a `QeegProjectionState` that
compares structurally `==` to any other replay of that same sequence,
regardless of process/machine/call-count — this is the "rebuild purely by
REPLAYING the ledger's append-only events... deterministic: same event
sequence -> identical projection" contract from this unit's own task
instruction.

READ-ONLY: nothing in this module writes back to a source ledger/store —
`apply_claim_fact`/`apply_evidence_fact`/`replay` only ever construct and
return a NEW `QeegProjectionState`; there is no function anywhere in this
module that accepts a *ledger* or *store* object and mutates it.

Idempotent replay: folding the same `ClaimFact` twice (byte-identical
dataclass equality) is a no-op — the second fold returns a
`QeegProjectionState` equal to the one after the first fold, never
duplicating an entry into `entity_claims`/`claims`. This mirrors
`saena_claim_evidence.ledger.append_claim`'s own "existing claim_id,
byte-identical content -> no-op replay" discipline, applied at the
read-model layer instead of the write-model layer.
"""

from __future__ import annotations

from collections.abc import Iterable

from saena_domain.qeeg.errors import CrossTenantProjectionAccessError, UnknownClaimError
from saena_domain.qeeg.models import (
    ClaimFact,
    EvidenceFact,
    QeegClaimView,
    QeegProjectionState,
)


def _claims_dict(state: QeegProjectionState) -> dict[str, QeegClaimView]:
    return dict(state.claims)


def _entity_claims_dict(state: QeegProjectionState) -> dict[str, tuple[str, ...]]:
    return dict(state.entity_claims)


def _guard_tenant(state: QeegProjectionState, fact_tenant_id: str) -> None:
    if state.tenant_id != fact_tenant_id:
        raise CrossTenantProjectionAccessError(
            "fact tenant_id does not match this projection's tenant_id",
            context={
                "projection_tenant_id": state.tenant_id,
                "fact_tenant_id": fact_tenant_id,
            },
        )


def apply_claim_fact(state: QeegProjectionState, fact: ClaimFact) -> QeegProjectionState:
    """Fold one `ClaimFact` into `state`, returning a NEW `QeegProjectionState`.

    Fail-closed tenant scoping: raises `CrossTenantProjectionAccessError`
    if `fact.tenant_id != state.tenant_id`.

    Idempotent: if `state` already carries a `QeegClaimView` for
    `fact.claim_id` whose (`entity_id`, `status`, `publishable`,
    `blocking_reasons`, `supporting_evidence_ids`) already match `fact`
    exactly AND `entity_claims` already lists this `claim_id` under this
    `entity_id`, this is a true no-op — `state` is returned UNCHANGED
    (same object identity), matching `saena_claim_evidence.ledger.
    _reevaluate`'s "no-op — no new entry — when nothing changed" rule at
    this projection layer. A claim whose `entity_id` changes across
    replayed facts (not expected from a real ledger, which never mutates
    `ExtractedClaim.entity_id` across a claim's own re-evaluated entries,
    but not structurally forbidden here) is re-indexed: removed from its
    old entity's claim list and added to the new one, keeping
    `entity_claims` consistent with the latest fact's `entity_id` — this
    replay engine takes no position on whether an upstream write-model
    permits that; it only guarantees replaying whatever sequence it is
    given deterministically reproduces the same state.
    """
    _guard_tenant(state, fact.tenant_id)

    claims = _claims_dict(state)
    existing = claims.get(fact.claim_id)
    new_view = QeegClaimView(
        claim_id=fact.claim_id,
        entity_id=fact.entity_id,
        status=fact.status,
        publishable=fact.publishable,
        blocking_reasons=fact.blocking_reasons,
        supporting_evidence_ids=fact.supporting_evidence_ids,
        evidence_ids=existing.evidence_ids if existing is not None else (),
    )

    entity_claims = _entity_claims_dict(state)
    old_entity_id = existing.entity_id if existing is not None else None

    if existing is not None and existing == new_view and old_entity_id == fact.entity_id:
        return state

    claims[fact.claim_id] = new_view

    if old_entity_id is not None and old_entity_id != fact.entity_id:
        old_list = entity_claims.get(old_entity_id, ())
        if fact.claim_id in old_list:
            entity_claims[old_entity_id] = tuple(c for c in old_list if c != fact.claim_id)

    current_list = entity_claims.get(fact.entity_id, ())
    if fact.claim_id not in current_list:
        entity_claims[fact.entity_id] = (*current_list, fact.claim_id)

    return QeegProjectionState(
        tenant_id=state.tenant_id,
        claims=tuple(sorted(claims.items())),
        entity_claims=tuple(sorted(entity_claims.items())),
    )


def apply_evidence_fact(state: QeegProjectionState, fact: EvidenceFact) -> QeegProjectionState:
    """Fold one `EvidenceFact` into `state`, returning a NEW `QeegProjectionState`.

    Fail-closed tenant scoping: raises `CrossTenantProjectionAccessError`
    if `fact.tenant_id != state.tenant_id`.

    Fail-closed referential integrity: raises `UnknownClaimError` if
    `fact.claim_id` has never been folded into this projection via
    `apply_claim_fact` — mirrors `saena_claim_evidence.ledger.
    append_evidence`'s own `EvidenceClaimMismatchError` ("evidence can
    never link to an unknown claim") at the read-model layer; a real
    replay sequence never produces this (evidence always follows its
    claim in the source ledger), so hitting this is a caller/ordering bug,
    not a normal branch — fail closed rather than silently creating a
    dangling claim stub.

    Idempotent: re-folding an `evidence_id` already present in the
    claim's `evidence_ids` tuple is a no-op (`state` returned unchanged);
    this is a pure link-existence fold — `EvidenceFact.link_status`
    itself does not change `QeegClaimView` (publishability is carried
    entirely by the OWNING claim's own `ClaimFact.publishable`/
    `blocking_reasons`, re-derived and re-folded by the caller exactly as
    `saena_claim_evidence.ledger.append_evidence`'s trailing re-evaluated
    claim entry already does at the write-model layer — this function
    only tracks "is this evidence_id linked to this claim_id", not a
    second, competing publishability computation).
    """
    _guard_tenant(state, fact.tenant_id)

    claims = _claims_dict(state)
    claim_view = claims.get(fact.claim_id)
    if claim_view is None:
        raise UnknownClaimError(
            f"claim_id {fact.claim_id!r} not found in this projection — evidence "
            "facts must be folded after their owning claim fact",
            context={"claim_id": fact.claim_id, "evidence_id": fact.evidence_id},
        )

    if fact.evidence_id in claim_view.evidence_ids:
        return state

    updated_view = QeegClaimView(
        claim_id=claim_view.claim_id,
        entity_id=claim_view.entity_id,
        status=claim_view.status,
        publishable=claim_view.publishable,
        blocking_reasons=claim_view.blocking_reasons,
        supporting_evidence_ids=claim_view.supporting_evidence_ids,
        evidence_ids=(*claim_view.evidence_ids, fact.evidence_id),
    )
    claims[fact.claim_id] = updated_view

    return QeegProjectionState(
        tenant_id=state.tenant_id,
        claims=tuple(sorted(claims.items())),
        entity_claims=state.entity_claims,
    )


def empty_projection(tenant_id: str) -> QeegProjectionState:
    """A fresh, empty `QeegProjectionState` scoped to `tenant_id` — the
    canonical starting point for `replay`."""
    return QeegProjectionState(tenant_id=tenant_id)


def replay(tenant_id: str, facts: Iterable[ClaimFact | EvidenceFact]) -> QeegProjectionState:
    """Rebuild a `QeegProjectionState` FROM SCRATCH by folding `facts`, in
    order, over an `empty_projection(tenant_id)`.

    This is the "rebuild purely by REPLAYING the ledger's append-only
    events" entry point: calling `replay(tenant_id, all_facts)` must
    always yield a state structurally `==` to whatever state incrementally
    folding those same facts one at a time (in the same order) via
    repeated `apply_claim_fact`/`apply_evidence_fact` calls would produce
    — both paths share the exact same two fold functions, so this holds by
    construction, not by a separate reconciliation step.
    """
    state = empty_projection(tenant_id)
    for fact in facts:
        if isinstance(fact, ClaimFact):
            state = apply_claim_fact(state, fact)
        else:
            state = apply_evidence_fact(state, fact)
    return state


def claims_by_entity(state: QeegProjectionState, entity_id: str) -> tuple[QeegClaimView, ...]:
    """Every `QeegClaimView` currently linked to `entity_id`, in
    first-linked order (empty tuple if `entity_id` has never been observed
    — never raises, mirrors `saena_claim_evidence.store.
    InMemoryClaimEvidenceStore.get_ledger`'s "nothing here" empty-state
    discipline for a collection-shaped query)."""
    claims = _claims_dict(state)
    entity_claims = _entity_claims_dict(state)
    claim_ids = entity_claims.get(entity_id, ())
    return tuple(claims[claim_id] for claim_id in claim_ids if claim_id in claims)


def evidence_by_claim(state: QeegProjectionState, claim_id: str) -> tuple[str, ...]:
    """The `evidence_id` tuple currently linked to `claim_id`.

    Raises `UnknownClaimError` if `claim_id` has never been observed by
    this projection — a specific-identifier lookup mirrors
    `saena_claim_evidence.store.InMemoryClaimEvidenceStore.
    get_claim_publishability`'s "raises for an unknown claim_id" choice
    (distinct from `claims_by_entity`'s collection-shaped empty-tuple
    discipline).
    """
    claim_view = _claims_dict(state).get(claim_id)
    if claim_view is None:
        raise UnknownClaimError(
            f"claim_id {claim_id!r} not found in this projection",
            context={"claim_id": claim_id},
        )
    return claim_view.evidence_ids


def publishability_of(state: QeegProjectionState, claim_id: str) -> QeegClaimView:
    """The current `QeegClaimView` (carrying `publishable`/
    `blocking_reasons`) for `claim_id`.

    Raises `UnknownClaimError` if `claim_id` has never been observed.
    """
    claim_view = _claims_dict(state).get(claim_id)
    if claim_view is None:
        raise UnknownClaimError(
            f"claim_id {claim_id!r} not found in this projection",
            context={"claim_id": claim_id},
        )
    return claim_view


__all__ = [
    "apply_claim_fact",
    "apply_evidence_fact",
    "claims_by_entity",
    "empty_projection",
    "evidence_by_claim",
    "publishability_of",
    "replay",
]

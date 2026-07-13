"""Unit tests for `saena_domain.qeeg.replay`.

Gates covered: deterministic replay + rebuild-from-scratch equivalence,
idempotent replay, tenant scoping + cross-tenant deny, publishability
reflected from the (already fail-closed) fact input, edge branches.
"""

from __future__ import annotations

import pytest
from qeeg_factories import TENANT_A, TENANT_B, build_claim_fact, build_evidence_fact
from saena_domain.qeeg.errors import CrossTenantProjectionAccessError, UnknownClaimError
from saena_domain.qeeg.models import ClaimFact, EvidenceFact, QeegLinkStatus, QeegProjectionState
from saena_domain.qeeg.replay import (
    apply_claim_fact,
    apply_evidence_fact,
    claims_by_entity,
    empty_projection,
    evidence_by_claim,
    publishability_of,
    replay,
)

# ---------------------------------------------------------------------------
# empty_projection / apply_claim_fact happy path
# ---------------------------------------------------------------------------


def test_empty_projection_is_empty() -> None:
    state = empty_projection(TENANT_A)
    assert state.tenant_id == TENANT_A
    assert state.claims == ()
    assert state.entity_claims == ()


def test_apply_claim_fact_adds_claim_and_entity_index() -> None:
    state = empty_projection(TENANT_A)
    fact = build_claim_fact()
    new_state = apply_claim_fact(state, fact)

    assert new_state is not state
    view = publishability_of(new_state, fact.claim_id)
    assert view.claim_id == fact.claim_id
    assert view.entity_id == fact.entity_id
    assert view.publishable is True
    assert view.evidence_ids == ()

    linked = claims_by_entity(new_state, fact.entity_id)
    assert linked == (view,)


def test_apply_claim_fact_returns_new_state_never_mutates_input() -> None:
    state = empty_projection(TENANT_A)
    fact = build_claim_fact()
    new_state = apply_claim_fact(state, fact)

    # original state is provably untouched
    assert state.claims == ()
    assert state.entity_claims == ()
    assert new_state.claims != ()


# ---------------------------------------------------------------------------
# apply_evidence_fact happy path + referential integrity
# ---------------------------------------------------------------------------


def test_apply_evidence_fact_links_evidence_to_claim() -> None:
    state = empty_projection(TENANT_A)
    claim_fact = build_claim_fact()
    state = apply_claim_fact(state, claim_fact)

    evidence_fact = build_evidence_fact()
    state = apply_evidence_fact(state, evidence_fact)

    assert evidence_by_claim(state, claim_fact.claim_id) == (evidence_fact.evidence_id,)


def test_apply_evidence_fact_unknown_claim_raises() -> None:
    state = empty_projection(TENANT_A)
    evidence_fact = build_evidence_fact(claim_id="claim-never-appended")

    with pytest.raises(UnknownClaimError) as exc_info:
        apply_evidence_fact(state, evidence_fact)

    assert exc_info.value.error_code == "saena.not_found.qeeg_claim"
    assert exc_info.value.context["claim_id"] == "claim-never-appended"


def test_apply_evidence_fact_does_not_affect_publishability() -> None:
    """The projection never recomputes publishability from EvidenceFact —
    it only tracks the evidence_id link; publishable/blocking_reasons are
    carried verbatim by the ClaimFact already folded in."""
    state = empty_projection(TENANT_A)
    claim_fact = build_claim_fact(publishable=False, blocking_reasons=("no_evidence",))
    state = apply_claim_fact(state, claim_fact)

    evidence_fact = build_evidence_fact(link_status=QeegLinkStatus.LINKED)
    state = apply_evidence_fact(state, evidence_fact)

    view = publishability_of(state, claim_fact.claim_id)
    assert view.publishable is False
    assert view.blocking_reasons == ("no_evidence",)
    assert view.evidence_ids == (evidence_fact.evidence_id,)


# ---------------------------------------------------------------------------
# Idempotent replay
# ---------------------------------------------------------------------------


def test_apply_claim_fact_byte_identical_refold_is_true_noop() -> None:
    state = empty_projection(TENANT_A)
    fact = build_claim_fact()
    state1 = apply_claim_fact(state, fact)
    state2 = apply_claim_fact(state1, fact)

    assert state2 is state1  # same object identity — a true no-op


def test_apply_evidence_fact_byte_identical_refold_is_true_noop() -> None:
    state = empty_projection(TENANT_A)
    claim_fact = build_claim_fact()
    state = apply_claim_fact(state, claim_fact)
    evidence_fact = build_evidence_fact()
    state1 = apply_evidence_fact(state, evidence_fact)
    state2 = apply_evidence_fact(state1, evidence_fact)

    assert state2 is state1


def test_replay_full_sequence_twice_is_idempotent() -> None:
    claim_fact = build_claim_fact()
    evidence_fact = build_evidence_fact()
    facts: list[ClaimFact | EvidenceFact] = [claim_fact, evidence_fact]

    state1 = replay(TENANT_A, facts)
    # replaying again from empty must reproduce the same structural state
    state2 = replay(TENANT_A, facts)

    assert state1 == state2


# ---------------------------------------------------------------------------
# Determinism / rebuild-from-scratch equivalence
# ---------------------------------------------------------------------------


def test_replay_equals_incremental_apply_same_order() -> None:
    claim_fact = build_claim_fact()
    evidence_fact = build_evidence_fact()

    incremental = empty_projection(TENANT_A)
    incremental = apply_claim_fact(incremental, claim_fact)
    incremental = apply_evidence_fact(incremental, evidence_fact)

    from_scratch = replay(TENANT_A, [claim_fact, evidence_fact])

    assert incremental == from_scratch


def test_replay_multiple_claims_and_evidence_deterministic() -> None:
    facts: list[ClaimFact | EvidenceFact] = [
        build_claim_fact(claim_id="claim-a", entity_id="entity-x"),
        build_claim_fact(claim_id="claim-b", entity_id="entity-x"),
        build_claim_fact(claim_id="claim-c", entity_id="entity-y"),
        build_evidence_fact(evidence_id="ev-1", claim_id="claim-a"),
        build_evidence_fact(evidence_id="ev-2", claim_id="claim-a"),
        build_evidence_fact(evidence_id="ev-3", claim_id="claim-b"),
    ]

    state_a = replay(TENANT_A, facts)
    state_b = replay(TENANT_A, list(facts))  # fresh list, same order/content

    assert state_a == state_b
    assert set(evidence_by_claim(state_a, "claim-a")) == {"ev-1", "ev-2"}
    assert evidence_by_claim(state_a, "claim-b") == ("ev-3",)
    linked_x = {view.claim_id for view in claims_by_entity(state_a, "entity-x")}
    assert linked_x == {"claim-a", "claim-b"}
    linked_y = {view.claim_id for view in claims_by_entity(state_a, "entity-y")}
    assert linked_y == {"claim-c"}


# ---------------------------------------------------------------------------
# Tenant scoping / cross-tenant deny
# ---------------------------------------------------------------------------


def test_apply_claim_fact_cross_tenant_raises() -> None:
    state = empty_projection(TENANT_A)
    fact = build_claim_fact(tenant_id=TENANT_B)

    with pytest.raises(CrossTenantProjectionAccessError) as exc_info:
        apply_claim_fact(state, fact)

    assert exc_info.value.error_code == "saena.auth.cross_tenant_denied"
    assert exc_info.value.context["projection_tenant_id"] == TENANT_A
    assert exc_info.value.context["fact_tenant_id"] == TENANT_B


def test_apply_evidence_fact_cross_tenant_raises() -> None:
    state = empty_projection(TENANT_A)
    state = apply_claim_fact(state, build_claim_fact())
    fact = build_evidence_fact(tenant_id=TENANT_B)

    with pytest.raises(CrossTenantProjectionAccessError):
        apply_evidence_fact(state, fact)


def test_replay_cross_tenant_fact_raises() -> None:
    facts = [build_claim_fact(tenant_id=TENANT_B)]
    with pytest.raises(CrossTenantProjectionAccessError):
        replay(TENANT_A, facts)


def test_two_tenants_never_share_state() -> None:
    state_a = replay(TENANT_A, [build_claim_fact(tenant_id=TENANT_A)])
    state_b = replay(TENANT_B, [build_claim_fact(tenant_id=TENANT_B)])

    assert state_a.tenant_id == TENANT_A
    assert state_b.tenant_id == TENANT_B
    assert state_a != state_b


# ---------------------------------------------------------------------------
# Query helpers — edge branches
# ---------------------------------------------------------------------------


def test_claims_by_entity_unknown_entity_returns_empty_tuple() -> None:
    state = empty_projection(TENANT_A)
    assert claims_by_entity(state, "entity-never-seen") == ()


def test_evidence_by_claim_unknown_claim_raises() -> None:
    state = empty_projection(TENANT_A)
    with pytest.raises(UnknownClaimError):
        evidence_by_claim(state, "claim-never-seen")


def test_publishability_of_unknown_claim_raises() -> None:
    state = empty_projection(TENANT_A)
    with pytest.raises(UnknownClaimError) as exc_info:
        publishability_of(state, "claim-never-seen")
    assert exc_info.value.context["claim_id"] == "claim-never-seen"


def test_apply_claim_fact_re_entitied_claim_reindexes() -> None:
    """A claim_id whose entity_id changes across replayed facts is
    re-indexed under the new entity and removed from the old one."""
    state = empty_projection(TENANT_A)
    state = apply_claim_fact(state, build_claim_fact(entity_id="entity-old"))
    state = apply_claim_fact(state, build_claim_fact(entity_id="entity-new"))

    assert claims_by_entity(state, "entity-old") == ()
    linked_new = claims_by_entity(state, "entity-new")
    assert len(linked_new) == 1
    assert linked_new[0].entity_id == "entity-new"


def test_apply_evidence_fact_duplicate_evidence_id_not_double_counted() -> None:
    state = empty_projection(TENANT_A)
    state = apply_claim_fact(state, build_claim_fact())
    state = apply_evidence_fact(state, build_evidence_fact(evidence_id="ev-1"))
    state = apply_evidence_fact(state, build_evidence_fact(evidence_id="ev-1"))

    assert evidence_by_claim(state, "claim-0001") == ("ev-1",)


def test_replay_empty_facts_returns_empty_projection() -> None:
    state = replay(TENANT_A, [])
    assert state == empty_projection(TENANT_A)


def test_qeeg_projection_state_equality_across_independent_replays() -> None:
    """Two structurally distinct QeegProjectionState objects built from the
    same fact sequence, independently, compare equal — proving the
    "identical projection" determinism contract at the object-equality
    level, not merely by construction inspection."""
    facts: list[ClaimFact | EvidenceFact] = [build_claim_fact(), build_evidence_fact()]
    state1 = replay(TENANT_A, facts)
    state2 = replay(TENANT_A, list(reversed(list(reversed(facts)))))
    assert state1 == state2
    assert isinstance(state1, QeegProjectionState)

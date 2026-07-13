"""Unit tests for `saena_claim_evidence.qeeg_projection` (w4-11).

Gates covered: deterministic replay + rebuild-from-scratch equivalence
over a REAL claim-evidence ledger/store, idempotent replay, tenant
scoping + cross-tenant deny, publishability reflected from the
fail-closed write-model, edge branches.
"""

from __future__ import annotations

import pytest
from claim_evidence_factories import NOW, PROJECT_A, TENANT_A, TENANT_B, build_claim, build_evidence
from saena_claim_evidence.errors import CrossTenantLedgerAccessError
from saena_claim_evidence.evaluation import EvidenceLinkStatus
from saena_claim_evidence.ledger import append_claim, append_evidence
from saena_claim_evidence.qeeg_projection import (
    build_qeeg_projection,
    claims_by_entity,
    evidence_by_claim,
    publishability_of,
    replay_qeeg_projection_from_store,
)
from saena_claim_evidence.store import InMemoryClaimEvidenceStore
from saena_domain.qeeg.errors import CrossTenantProjectionAccessError, UnknownClaimError
from saena_domain.qeeg.models import QeegLinkStatus

# ---------------------------------------------------------------------------
# Happy path: store -> ledger -> QEEG projection
# ---------------------------------------------------------------------------


def test_replay_qeeg_projection_from_store_publishable_claim() -> None:
    store = InMemoryClaimEvidenceStore()
    claim = build_claim()
    store.append_claim(TENANT_A, claim)
    evidence = build_evidence()
    store.append_evidence(TENANT_A, evidence, now=NOW)

    state = replay_qeeg_projection_from_store(store, tenant_id=TENANT_A, project_id=PROJECT_A)

    view = publishability_of(state, claim.claim_id)
    assert view.claim_id == claim.claim_id
    assert view.entity_id == claim.entity_id
    assert view.publishable is True
    assert view.blocking_reasons == ()
    assert view.supporting_evidence_ids == (evidence.evidence_id,)
    assert view.evidence_ids == (evidence.evidence_id,)


def test_replay_qeeg_projection_claim_without_evidence_is_not_publishable() -> None:
    store = InMemoryClaimEvidenceStore()
    claim = build_claim()
    store.append_claim(TENANT_A, claim)

    state = replay_qeeg_projection_from_store(store, tenant_id=TENANT_A, project_id=PROJECT_A)

    view = publishability_of(state, claim.claim_id)
    assert view.publishable is False
    assert view.blocking_reasons == ("no_evidence",)
    assert view.evidence_ids == ()


def test_claims_by_entity_reflects_ledger() -> None:
    store = InMemoryClaimEvidenceStore()
    claim = build_claim()
    store.append_claim(TENANT_A, claim)

    state = replay_qeeg_projection_from_store(store, tenant_id=TENANT_A, project_id=PROJECT_A)

    linked = claims_by_entity(state, claim.entity_id)
    assert len(linked) == 1
    assert linked[0].claim_id == claim.claim_id


def test_evidence_by_claim_reflects_ledger() -> None:
    store = InMemoryClaimEvidenceStore()
    claim = build_claim()
    store.append_claim(TENANT_A, claim)
    evidence = build_evidence()
    store.append_evidence(TENANT_A, evidence, now=NOW)

    state = replay_qeeg_projection_from_store(store, tenant_id=TENANT_A, project_id=PROJECT_A)

    assert evidence_by_claim(state, claim.claim_id) == (evidence.evidence_id,)


# ---------------------------------------------------------------------------
# Publishability reflected from the fail-closed write-model
# ---------------------------------------------------------------------------


def test_blocked_evidence_link_status_still_publishable_if_another_evidence_supports() -> None:
    """The write-model's own fail-closed evaluation decides publishability
    — the projection only ever replays it verbatim, never recomputes it."""
    store = InMemoryClaimEvidenceStore()
    claim = build_claim()
    store.append_claim(TENANT_A, claim)
    evidence_1 = build_evidence(evidence_id="evidence-0001")
    store.append_evidence(TENANT_A, evidence_1, now=NOW)
    evidence_2 = build_evidence(evidence_id="evidence-0002")
    store.append_evidence(TENANT_A, evidence_2, now=NOW)

    store.set_evidence_link_status(
        TENANT_A,
        PROJECT_A,
        evidence_id="evidence-0001",
        status=EvidenceLinkStatus.BLOCKED,
        now=NOW,
    )

    state = replay_qeeg_projection_from_store(store, tenant_id=TENANT_A, project_id=PROJECT_A)
    view = publishability_of(state, claim.claim_id)
    # write-model re-evaluated: evidence_2 still LINKED+fresh -> still publishable
    assert view.publishable is True
    assert view.supporting_evidence_ids == ("evidence-0002",)


def test_all_evidence_blocked_claim_becomes_unpublishable_in_projection() -> None:
    store = InMemoryClaimEvidenceStore()
    claim = build_claim()
    store.append_claim(TENANT_A, claim)
    evidence = build_evidence()
    store.append_evidence(TENANT_A, evidence, now=NOW)

    store.set_evidence_link_status(
        TENANT_A,
        PROJECT_A,
        evidence_id=evidence.evidence_id,
        status=EvidenceLinkStatus.BLOCKED,
        now=NOW,
    )

    state = replay_qeeg_projection_from_store(store, tenant_id=TENANT_A, project_id=PROJECT_A)
    view = publishability_of(state, claim.claim_id)
    assert view.publishable is False
    assert "blocked" in view.blocking_reasons


# ---------------------------------------------------------------------------
# Determinism / rebuild-from-scratch equivalence
# ---------------------------------------------------------------------------


def test_build_qeeg_projection_rebuild_from_scratch_equals_live_replay() -> None:
    store = InMemoryClaimEvidenceStore()
    claim = build_claim()
    store.append_claim(TENANT_A, claim)
    evidence = build_evidence()
    store.append_evidence(TENANT_A, evidence, now=NOW)

    state_live = replay_qeeg_projection_from_store(store, tenant_id=TENANT_A, project_id=PROJECT_A)

    ledger_state = store.get_ledger(TENANT_A, PROJECT_A)
    state_rebuilt = build_qeeg_projection(TENANT_A, ledger_state)

    assert state_live == state_rebuilt


def test_build_qeeg_projection_rebuilt_twice_is_deterministic() -> None:
    ledger_state, _ = append_claim((), build_claim())
    ledger_state, _ = append_evidence(ledger_state, build_evidence(), link_statuses={}, now=NOW)

    state_1 = build_qeeg_projection(TENANT_A, ledger_state)
    state_2 = build_qeeg_projection(TENANT_A, ledger_state)

    assert state_1 == state_2


# ---------------------------------------------------------------------------
# Idempotent replay
# ---------------------------------------------------------------------------


def test_build_qeeg_projection_idempotent_across_repeated_calls() -> None:
    store = InMemoryClaimEvidenceStore()
    claim = build_claim()
    store.append_claim(TENANT_A, claim)
    evidence = build_evidence()
    store.append_evidence(TENANT_A, evidence, now=NOW)

    ledger_state = store.get_ledger(TENANT_A, PROJECT_A)
    first = build_qeeg_projection(TENANT_A, ledger_state)
    second = build_qeeg_projection(TENANT_A, ledger_state)
    third = build_qeeg_projection(TENANT_A, ledger_state)

    assert first == second == third


def test_build_qeeg_projection_republish_entry_not_double_counted() -> None:
    """append_evidence's trailing re-evaluated claim entry (ledger.py
    "fail-closed-on-mutation") appends a SECOND claim-kind entry for the
    same claim_id — the projection must fold this without duplicating the
    claim in entity_claims or evidence_ids."""
    store = InMemoryClaimEvidenceStore()
    claim = build_claim()
    store.append_claim(TENANT_A, claim)
    evidence = build_evidence()
    store.append_evidence(TENANT_A, evidence, now=NOW)

    ledger_state = store.get_ledger(TENANT_A, PROJECT_A)
    claim_entries = [e for e in ledger_state if e.kind == "claim"]
    assert len(claim_entries) == 2  # original append + re-evaluated republish

    state = build_qeeg_projection(TENANT_A, ledger_state)
    linked = claims_by_entity(state, claim.entity_id)
    assert len(linked) == 1
    assert linked[0].evidence_ids == (evidence.evidence_id,)


# ---------------------------------------------------------------------------
# Tenant scoping / cross-tenant deny
# ---------------------------------------------------------------------------


def test_store_append_cross_tenant_denied_before_projection_ever_sees_it() -> None:
    store = InMemoryClaimEvidenceStore()
    claim = build_claim(tenant_id=TENANT_A)
    with pytest.raises(CrossTenantLedgerAccessError):
        store.append_claim(TENANT_B, claim)


def test_build_qeeg_projection_filters_out_foreign_tenant_entries() -> None:
    """Defense-in-depth: even if a caller passed a mixed-tenant
    ledger_state (never produced by InMemoryClaimEvidenceStore itself,
    which already tenant-gates at append time), build_qeeg_projection only
    folds entries whose OWN tenant_id matches the requested tenant_id."""
    ledger_state, _ = append_claim((), build_claim(tenant_id=TENANT_A))
    foreign_claim = build_claim(
        tenant_id=TENANT_B, claim_id="claim-foreign", entity_id="entity-foreign"
    )
    ledger_state, _ = append_claim(ledger_state, foreign_claim)

    state = build_qeeg_projection(TENANT_A, ledger_state)

    assert state.tenant_id == TENANT_A
    with pytest.raises(UnknownClaimError):
        publishability_of(state, "claim-foreign")


def test_replay_qeeg_projection_from_store_is_tenant_scoped() -> None:
    store = InMemoryClaimEvidenceStore()
    claim_a = build_claim(tenant_id=TENANT_A)
    store.append_claim(TENANT_A, claim_a)

    state_a = replay_qeeg_projection_from_store(store, tenant_id=TENANT_A, project_id=PROJECT_A)
    state_b = replay_qeeg_projection_from_store(store, tenant_id=TENANT_B, project_id=PROJECT_A)

    assert publishability_of(state_a, claim_a.claim_id) is not None
    with pytest.raises(UnknownClaimError):
        publishability_of(state_b, claim_a.claim_id)


def test_build_qeeg_projection_never_calls_store_write_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """READ-ONLY contract: replaying via the store wrapper must never call
    any of the store's mutating methods."""
    store = InMemoryClaimEvidenceStore()
    claim = build_claim()
    store.append_claim(TENANT_A, claim)

    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("qeeg projection must never call a write method")

    monkeypatch.setattr(store, "append_claim", _fail)
    monkeypatch.setattr(store, "append_evidence", _fail)
    monkeypatch.setattr(store, "set_evidence_link_status", _fail)

    # must not raise
    replay_qeeg_projection_from_store(store, tenant_id=TENANT_A, project_id=PROJECT_A)


# ---------------------------------------------------------------------------
# Edge branches
# ---------------------------------------------------------------------------


def test_build_qeeg_projection_empty_ledger() -> None:
    state = build_qeeg_projection(TENANT_A, ())
    assert state.tenant_id == TENANT_A
    assert state.claims == ()


def test_replay_qeeg_projection_unknown_project_returns_empty_projection() -> None:
    store = InMemoryClaimEvidenceStore()
    state = replay_qeeg_projection_from_store(
        store, tenant_id=TENANT_A, project_id="project-never-seen"
    )
    assert state.claims == ()


def test_build_qeeg_projection_explicit_link_statuses_passthrough() -> None:
    ledger_state, _ = append_claim((), build_claim())
    link_statuses: dict[str, EvidenceLinkStatus] = {}
    ledger_state, _ = append_evidence(
        ledger_state, build_evidence(), link_statuses=link_statuses, now=NOW
    )

    state = build_qeeg_projection(TENANT_A, ledger_state, link_statuses=link_statuses)
    view = publishability_of(state, "claim-0001")
    assert view.evidence_ids == ("evidence-0001",)


def test_qeeg_link_status_enum_values_match_write_model() -> None:
    assert QeegLinkStatus.LINKED.value == EvidenceLinkStatus.LINKED.value
    assert QeegLinkStatus.BLOCKED.value == EvidenceLinkStatus.BLOCKED.value


def test_qeeg_projection_never_reads_claim_text_or_excerpt() -> None:
    """No PII: build a claim/evidence with distinctive proprietary-looking
    text, and assert none of it appears anywhere in the projected state's
    repr (the projection has no field for it, but this test additionally
    guards against a future accidental leak via str/repr)."""
    store = InMemoryClaimEvidenceStore()
    claim = build_claim(claim_text="PROPRIETARY-SECRET-CLAIM-TEXT-MARKER")
    store.append_claim(TENANT_A, claim)
    evidence = build_evidence(excerpt="PROPRIETARY-SECRET-EXCERPT-MARKER")
    store.append_evidence(TENANT_A, evidence, now=NOW)

    state = replay_qeeg_projection_from_store(store, tenant_id=TENANT_A, project_id=PROJECT_A)

    dump = repr(state)
    assert "PROPRIETARY-SECRET-CLAIM-TEXT-MARKER" not in dump
    assert "PROPRIETARY-SECRET-EXCERPT-MARKER" not in dump


def test_apply_claim_fact_cross_tenant_error_propagates_through_build() -> None:
    """build_qeeg_projection's filter is defense-in-depth on TOP of the
    fold engine's own guard — this test proves the underlying guard is
    still reachable/raising for a caller that bypasses the filter by
    calling saena_domain.qeeg directly with a foreign-tenant fact (already
    covered in tests/unit/domain_qeeg, re-asserted here at the service
    integration boundary for completeness)."""
    from saena_domain.qeeg.models import ClaimFact
    from saena_domain.qeeg.replay import apply_claim_fact, empty_projection

    state = empty_projection(TENANT_A)
    foreign_fact = ClaimFact(
        tenant_id=TENANT_B,
        project_id=PROJECT_A,
        claim_id="claim-x",
        entity_id="entity-x",
        status="active",
        publishable=True,
        blocking_reasons=(),
        supporting_evidence_ids=(),
    )
    with pytest.raises(CrossTenantProjectionAccessError):
        apply_claim_fact(state, foreign_fact)

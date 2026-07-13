"""`InMemoryClaimEvidenceStore` — tenant scoping + cross-tenant default-DENY."""

from __future__ import annotations

import pytest
from claim_evidence_factories import NOW, PROJECT_A, TENANT_A, TENANT_B, build_claim, build_evidence
from saena_claim_evidence import (
    ClaimNotFoundError,
    CrossTenantLedgerAccessError,
    EvidenceFreshnessPolicy,
    EvidenceLinkStatus,
    InMemoryClaimEvidenceStore,
)

POLICY = EvidenceFreshnessPolicy(max_age_seconds=3600)


def test_append_claim_rejects_a_claim_captured_under_a_different_tenant() -> None:
    store = InMemoryClaimEvidenceStore()
    claim = build_claim(tenant_id=TENANT_A)

    with pytest.raises(CrossTenantLedgerAccessError):
        store.append_claim(TENANT_B, claim)


def test_append_evidence_rejects_evidence_captured_under_a_different_tenant() -> None:
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_A, build_claim(tenant_id=TENANT_A))
    evidence = build_evidence(tenant_id=TENANT_A)

    with pytest.raises(CrossTenantLedgerAccessError):
        store.append_evidence(TENANT_B, evidence, now=NOW, policy=POLICY)


def test_get_ledger_never_leaks_a_different_tenants_data() -> None:
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_A, build_claim(tenant_id=TENANT_A))

    assert store.get_ledger(TENANT_B, PROJECT_A) == ()
    assert len(store.get_ledger(TENANT_A, PROJECT_A)) == 1


def test_get_claim_publishability_never_leaks_a_different_tenants_claim() -> None:
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_A, build_claim(tenant_id=TENANT_A))

    with pytest.raises(ClaimNotFoundError):
        store.get_claim_publishability(TENANT_B, PROJECT_A, "claim-0001")


def test_get_claim_publishability_round_trips_for_the_owning_tenant() -> None:
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_A, build_claim(tenant_id=TENANT_A))

    result = store.get_claim_publishability(TENANT_A, PROJECT_A, "claim-0001")
    assert result.publishable is False
    assert result.blocking_reasons == ("no_evidence",)


def test_two_tenants_can_use_the_same_project_id_independently() -> None:
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_A, build_claim(tenant_id=TENANT_A, project_id=PROJECT_A))
    store.append_claim(TENANT_B, build_claim(tenant_id=TENANT_B, project_id=PROJECT_A))

    ledger_a = store.get_ledger(TENANT_A, PROJECT_A)
    ledger_b = store.get_ledger(TENANT_B, PROJECT_A)
    assert len(ledger_a) == 1
    assert len(ledger_b) == 1
    assert ledger_a[0].tenant_id == TENANT_A
    assert ledger_b[0].tenant_id == TENANT_B


def test_full_happy_path_append_claim_then_evidence_then_read_back() -> None:
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_A, build_claim(tenant_id=TENANT_A))
    store.append_evidence(TENANT_A, build_evidence(tenant_id=TENANT_A), now=NOW, policy=POLICY)

    result = store.get_claim_publishability(TENANT_A, PROJECT_A, "claim-0001")
    assert result.publishable is True
    assert result.supporting_evidence_ids == ("evidence-0001",)


def test_set_evidence_link_status_updates_the_stores_ledger() -> None:
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_A, build_claim(tenant_id=TENANT_A))
    store.append_evidence(TENANT_A, build_evidence(tenant_id=TENANT_A), now=NOW, policy=POLICY)
    assert store.get_claim_publishability(TENANT_A, PROJECT_A, "claim-0001").publishable is True

    store.set_evidence_link_status(
        TENANT_A,
        PROJECT_A,
        evidence_id="evidence-0001",
        status=EvidenceLinkStatus.BLOCKED,
        now=NOW,
        policy=POLICY,
    )

    result = store.get_claim_publishability(TENANT_A, PROJECT_A, "claim-0001")
    assert result.publishable is False
    assert result.blocking_reasons == ("blocked",)


def test_get_ledger_for_unknown_project_returns_empty_tuple_not_an_error() -> None:
    store = InMemoryClaimEvidenceStore()
    assert store.get_ledger(TENANT_A, "project-never-seen") == ()

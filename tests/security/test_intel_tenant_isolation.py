"""Wave-4 intelligence: cross-tenant isolation, default-DENY (w4-16).

Mission constraint (verbatim, repeated across every w4-0x package this
module exercises): "tenant_id discriminator mandatory; cross-tenant
default-DENY" — and, more specifically, existence must never leak: a
record that belongs to a DIFFERENT tenant must be indistinguishable from a
record that never existed at all. This module proves that discipline holds
for every Wave-4 intelligence store this suite has access to, plus the
`chatgpt-observer` raw-artifact gateway (the boundary storing the raw
content those stores only ever reference):

1. `saena_entity_resolution.store.InMemoryEntityGraphStore`
2. `saena_demand_graph.store.InMemoryDemandGraphStore`
3. `saena_claim_evidence.store.InMemoryClaimEvidenceStore`
4. `saena_chatgpt_observer.artifact_gateway.FakeArtifactGateway`

For each store this module proves BOTH halves of the guard:
  (a) tenant B genuinely cannot read tenant A's own data (real records
      really were stored, under a different key), and
  (b) tenant B's error for "my project_id" and tenant B's error for
      "tenant A's project_id" are STRUCTURALLY IDENTICAL (same exception
      type + same error_code) — the "existence is not leaked" half a naive
      "tenant mismatch -> different error than not-found" implementation
      would fail.

Every test pins one store's cross-tenant guard by name in its own
docstring and fails if that guard is deleted/bypassed (a deleted guard
would either let tenant B read tenant A's data outright, or raise a
DIFFERENT exception than the genuinely-nonexistent case, breaking the
identical-error assertion).
"""

from __future__ import annotations

import pytest
from saena_chatgpt_observer.artifact_gateway import FakeArtifactGateway, RawArtifactRef
from saena_chatgpt_observer.errors import CrossTenantObservationError
from saena_claim_evidence.errors import ClaimNotFoundError, CrossTenantLedgerAccessError
from saena_claim_evidence.evaluation import EvidenceFreshnessPolicy
from saena_claim_evidence.store import InMemoryClaimEvidenceStore
from saena_demand_graph.builder import build_demand_graph
from saena_demand_graph.errors import CrossTenantDemandGraphError, DemandGraphNotFoundError
from saena_demand_graph.records import FirstPartyMaterial, MaterialSourceKind
from saena_demand_graph.store import InMemoryDemandGraphStore
from saena_entity_resolution.canonicalize import AliasGroup, EntityType, resolve_entities
from saena_entity_resolution.errors import CrossTenantEntityAccessError, EntityGraphNotFoundError
from saena_entity_resolution.graph import EntityGraph
from saena_entity_resolution.store import InMemoryEntityGraphStore
from saena_schemas.domain.evidence_record_v1 import EvidenceRecord
from saena_schemas.domain.extracted_claim_v1 import ExtractedClaim
from saena_schemas.domain.extracted_claim_v1 import Status as ClaimStatus

TENANT_A = "acme-co"
TENANT_B = "globex-co"
PROJECT_A = "proj-alpha"
PROJECT_NEVER_EXISTS = "proj-never-existed"

NOW_ISO = "2026-07-13T12:00:00Z"


def _make_entity_graph(*, tenant_id: str = TENANT_A, project_id: str = PROJECT_A) -> EntityGraph:
    result = resolve_entities(
        tenant_id=tenant_id,
        project_id=project_id,
        alias_groups=(
            AliasGroup(
                entity_id="entity-0001",
                entity_type=EntityType.product,
                canonical_name="Acme Widget",
                aliases=("acme widget", "the widget"),
                is_owned=True,
            ),
        ),
        clock=lambda: NOW_ISO,
    )
    return EntityGraph(
        tenant_id=result.tenant_id,
        project_id=result.project_id,
        graph_version=result.graph_version,
        provenance_ref=f"sha256:{'b' * 64}",
        entities=result.entities,
    )


def _make_demand_graph(*, tenant_id: str = TENANT_A, project_id: str = PROJECT_A):
    material = FirstPartyMaterial(
        material_id="m1",
        source_kind=MaterialSourceKind.SALES_TRANSCRIPT,
        text="what is your pricing plan",
        locale="en-US",
        provenance_ref="doc://sales/call-1",
    )
    return build_demand_graph(tenant_id=tenant_id, project_id=project_id, materials=(material,))


def _make_claim(*, tenant_id: str = TENANT_A, project_id: str = PROJECT_A) -> ExtractedClaim:
    return ExtractedClaim(
        tenant_id=tenant_id,  # type: ignore[arg-type]
        project_id=project_id,  # type: ignore[arg-type]
        claim_id="claim-0001",
        entity_id="entity-0001",
        claim_text="The product supports SSO via SAML 2.0.",
        status=ClaimStatus.active,
        effective_from=NOW_ISO,  # type: ignore[arg-type]
        created_at=NOW_ISO,  # type: ignore[arg-type]
    )


def _make_evidence(*, tenant_id: str = TENANT_A, project_id: str = PROJECT_A) -> EvidenceRecord:
    return EvidenceRecord(
        tenant_id=tenant_id,  # type: ignore[arg-type]
        project_id=project_id,  # type: ignore[arg-type]
        evidence_id="evidence-0001",
        claim_id="claim-0001",
        source_uri="https://docs.example.com/security/sso",  # type: ignore[arg-type]
        excerpt="SAML 2.0 SSO is supported on the Enterprise plan.",
        freshness_checked_at=NOW_ISO,  # type: ignore[arg-type]
        content_hash=f"sha256:{'a' * 64}",  # type: ignore[arg-type]
    )


# --- 1. saena_entity_resolution.store.InMemoryEntityGraphStore ---


def test_entity_graph_store_refuses_to_store_under_a_mismatched_tenant() -> None:
    """Pins `InMemoryEntityGraphStore.put`'s `graph.tenant_id != tenant_id`
    guard. Fails if deleted: tenant B could plant a graph under tenant A's
    own tenant_id key by simply calling `put(tenant_id="tenant-a", ...)"""
    store = InMemoryEntityGraphStore()
    graph = _make_entity_graph(tenant_id=TENANT_A)
    with pytest.raises(CrossTenantEntityAccessError):
        store.put(TENANT_B, PROJECT_A, graph)


def test_entity_graph_store_cross_tenant_read_is_identical_error_to_never_existed() -> None:
    """Pins `InMemoryEntityGraphStore.get`'s "never leak cross-tenant
    existence" discipline. Fails if a naive implementation instead raised a
    different error (or returned data) for "exists under tenant A" versus
    "never existed anywhere" when queried AS tenant B — a real regression
    class (existence-oracle) this identical-error assertion directly
    detects.
    """
    store = InMemoryEntityGraphStore()
    store.put(TENANT_A, PROJECT_A, _make_entity_graph(tenant_id=TENANT_A))

    with pytest.raises(EntityGraphNotFoundError) as cross_tenant_exc:
        store.get(TENANT_B, PROJECT_A)
    with pytest.raises(EntityGraphNotFoundError) as never_existed_exc:
        store.get(TENANT_B, PROJECT_NEVER_EXISTS)

    assert type(cross_tenant_exc.value) is type(never_existed_exc.value)
    assert cross_tenant_exc.value.error_code == never_existed_exc.value.error_code
    assert cross_tenant_exc.value.error_code == "saena.not_found.entity_graph"


def test_entity_graph_store_tenant_a_can_read_its_own_data_back() -> None:
    """Negative control: tenant A reading its OWN data must succeed —
    proves the store is a real functioning cache, not a blanket deny that
    would make the cross-tenant assertions above vacuous."""
    store = InMemoryEntityGraphStore()
    graph = _make_entity_graph(tenant_id=TENANT_A)
    store.put(TENANT_A, PROJECT_A, graph)
    assert store.get(TENANT_A, PROJECT_A) is graph


# --- 2. saena_demand_graph.store.InMemoryDemandGraphStore ---


def test_demand_graph_store_refuses_to_store_under_a_mismatched_tenant() -> None:
    """Pins `InMemoryDemandGraphStore.put`'s `graph.tenant_id != tenant_id`
    guard."""
    store = InMemoryDemandGraphStore()
    graph = _make_demand_graph(tenant_id=TENANT_A)
    with pytest.raises(CrossTenantDemandGraphError):
        store.put(TENANT_B, PROJECT_A, graph)


def test_demand_graph_store_cross_tenant_read_is_identical_error_to_never_existed() -> None:
    """Pins `InMemoryDemandGraphStore.get`'s never-leak-existence
    discipline, same shape as the entity-graph store's own proof above."""
    store = InMemoryDemandGraphStore()
    store.put(TENANT_A, PROJECT_A, _make_demand_graph(tenant_id=TENANT_A))

    with pytest.raises(DemandGraphNotFoundError) as cross_tenant_exc:
        store.get(TENANT_B, PROJECT_A)
    with pytest.raises(DemandGraphNotFoundError) as never_existed_exc:
        store.get(TENANT_B, PROJECT_NEVER_EXISTS)

    assert type(cross_tenant_exc.value) is type(never_existed_exc.value)
    assert cross_tenant_exc.value.error_code == never_existed_exc.value.error_code
    assert cross_tenant_exc.value.error_code == "saena.not_found.demand_graph"


def test_demand_graph_store_tenant_a_can_read_its_own_data_back() -> None:
    """Negative control for the demand-graph store."""
    store = InMemoryDemandGraphStore()
    graph = _make_demand_graph(tenant_id=TENANT_A)
    store.put(TENANT_A, PROJECT_A, graph)
    assert store.get(TENANT_A, PROJECT_A) is graph


# --- 3. saena_claim_evidence.store.InMemoryClaimEvidenceStore ---


def test_claim_evidence_store_refuses_to_append_claim_under_a_mismatched_tenant() -> None:
    """Pins `InMemoryClaimEvidenceStore.append_claim`'s
    `claim.tenant_id != tenant_id` guard (`CrossTenantLedgerAccessError`)."""
    store = InMemoryClaimEvidenceStore()
    claim = _make_claim(tenant_id=TENANT_A)
    with pytest.raises(CrossTenantLedgerAccessError):
        store.append_claim(TENANT_B, claim)


def test_claim_evidence_store_refuses_to_append_evidence_under_a_mismatched_tenant() -> None:
    """Pins `InMemoryClaimEvidenceStore.append_evidence`'s
    `evidence.tenant_id != tenant_id` guard."""
    from datetime import UTC, datetime

    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_A, _make_claim(tenant_id=TENANT_A))
    evidence = _make_evidence(tenant_id=TENANT_A)
    with pytest.raises(CrossTenantLedgerAccessError):
        store.append_evidence(
            TENANT_B,
            evidence,
            now=datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC),
            policy=EvidenceFreshnessPolicy(max_age_seconds=86400),
        )


def test_claim_evidence_store_cross_tenant_publishability_read_is_identical_error_to_never_existed() -> (  # noqa: E501
    None
):
    """Pins `InMemoryClaimEvidenceStore.get_claim_publishability`'s
    never-leak-existence discipline: a claim appended under tenant A must
    be indistinguishable, when queried as tenant B, from a `claim_id` that
    was never appended under ANY tenant at all — both raise
    `ClaimNotFoundError` with an identical `error_code`.
    """
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_A, _make_claim(tenant_id=TENANT_A))

    with pytest.raises(ClaimNotFoundError) as cross_tenant_exc:
        store.get_claim_publishability(TENANT_B, PROJECT_A, "claim-0001")
    with pytest.raises(ClaimNotFoundError) as never_existed_exc:
        store.get_claim_publishability(TENANT_B, PROJECT_NEVER_EXISTS, "claim-never-existed")

    assert type(cross_tenant_exc.value) is type(never_existed_exc.value)
    assert cross_tenant_exc.value.error_code == never_existed_exc.value.error_code
    assert cross_tenant_exc.value.error_code == "saena.not_found.claim"


def test_claim_evidence_store_tenant_a_can_read_its_own_claim_publishability_back() -> None:
    """Negative control for the claim-evidence ledger store."""
    store = InMemoryClaimEvidenceStore()
    store.append_claim(TENANT_A, _make_claim(tenant_id=TENANT_A))
    publishability = store.get_claim_publishability(TENANT_A, PROJECT_A, "claim-0001")
    assert publishability.claim_id == "claim-0001"


# --- 4. saena_chatgpt_observer.artifact_gateway.FakeArtifactGateway ---


def test_artifact_gateway_cross_tenant_read_is_identical_error_to_never_existed() -> None:
    """Pins `FakeArtifactGateway.get_raw_artifact`'s never-leak-existence
    discipline (`CrossTenantObservationError`) — the single gateway raw
    observation content flows through. Tenant B reading tenant A's real,
    just-stored artifact ref must raise the SAME exception type/error_code
    as tenant B reading a well-formed but entirely fabricated ref.
    """
    gateway = FakeArtifactGateway()
    real_ref = gateway.put_raw_artifact(tenant_id=TENANT_A, raw_content=b"<html>secret</html>")
    fabricated_ref = RawArtifactRef(
        raw_object_ref=f"artifact://{TENANT_A}/{'0' * 64}", artifact_hash=f"sha256:{'0' * 64}"
    )

    with pytest.raises(CrossTenantObservationError) as cross_tenant_exc:
        gateway.get_raw_artifact(tenant_id=TENANT_B, ref=real_ref)
    with pytest.raises(CrossTenantObservationError) as never_existed_exc:
        gateway.get_raw_artifact(tenant_id=TENANT_B, ref=fabricated_ref)

    assert type(cross_tenant_exc.value) is type(never_existed_exc.value)
    assert cross_tenant_exc.value.error_code == never_existed_exc.value.error_code
    assert cross_tenant_exc.value.error_code == "saena.auth.cross_tenant_denied"


def test_artifact_gateway_tenant_a_can_read_its_own_raw_artifact_back() -> None:
    """Negative control: tenant A reading its own just-stored raw artifact
    back must succeed and return the exact bytes stored — proves the
    gateway is a real store, not a blanket deny."""
    gateway = FakeArtifactGateway()
    ref = gateway.put_raw_artifact(tenant_id=TENANT_A, raw_content=b"<html>ok</html>")
    assert gateway.get_raw_artifact(tenant_id=TENANT_A, ref=ref) == b"<html>ok</html>"


def test_artifact_gateway_ref_from_a_different_tenants_namespace_is_rejected_even_if_well_formed() -> (  # noqa: E501
    None
):
    """Adversarial variant: an attacker (or a buggy caller) hand-crafts a
    `RawArtifactRef` that LOOKS like it belongs to tenant A (correct
    `artifact://` scheme, correct hash length) but is queried by tenant B —
    proves the gateway checks the ref's OWN tenant-scoped prefix
    structurally, not merely "does this hash exist somewhere in the whole
    store" (which would leak cross-tenant existence via a crafted-but-
    unstored ref returning a DIFFERENT error than a genuinely stored one)."""
    gateway = FakeArtifactGateway()
    gateway.put_raw_artifact(tenant_id=TENANT_A, raw_content=b"<html>real</html>")
    crafted_ref = RawArtifactRef(
        raw_object_ref=f"artifact://{TENANT_A}/{'f' * 64}", artifact_hash=f"sha256:{'f' * 64}"
    )
    with pytest.raises(CrossTenantObservationError):
        gateway.get_raw_artifact(tenant_id=TENANT_B, ref=crafted_ref)

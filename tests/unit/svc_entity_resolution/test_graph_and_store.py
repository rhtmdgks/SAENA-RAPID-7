"""Unit tests: `saena_entity_resolution.graph` / `.store` — tenant scoping
and cross-tenant deny-by-default."""

from __future__ import annotations

import pytest
from saena_entity_resolution.canonicalize import AliasGroup, EntityType
from saena_entity_resolution.errors import CrossTenantEntityAccessError, EntityGraphNotFoundError
from saena_entity_resolution.graph import build_entity_graph, recompute_graph_version
from saena_entity_resolution.store import InMemoryEntityGraphStore

_PROVENANCE_REF = "sha256:" + "c" * 64


def _groups() -> tuple[AliasGroup, ...]:
    return (
        AliasGroup(
            entity_id="e1",
            entity_type=EntityType.brand,
            canonical_name="Acme",
            aliases=("acme",),
            is_owned=True,
        ),
    )


class TestBuildEntityGraph:
    def test_build_entity_graph_carries_provenance_ref(self) -> None:
        graph = build_entity_graph(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=_groups(),
            provenance_ref=_PROVENANCE_REF,
        )
        assert graph.provenance_ref == _PROVENANCE_REF
        assert graph.entity_count == 1

    def test_recompute_graph_version_matches_original(self) -> None:
        groups = _groups()
        graph = build_entity_graph(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=groups,
            provenance_ref=_PROVENANCE_REF,
        )
        assert recompute_graph_version(graph, groups) == graph.graph_version

    def test_entities_owned_by_tenant_returns_entities_for_matching_tenant(self) -> None:
        graph = build_entity_graph(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=_groups(),
            provenance_ref=_PROVENANCE_REF,
        )
        assert graph.entities_owned_by_tenant("acme-corp") == graph.entities

    def test_entities_owned_by_tenant_denies_cross_tenant_read(self) -> None:
        graph = build_entity_graph(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=_groups(),
            provenance_ref=_PROVENANCE_REF,
        )
        with pytest.raises(CrossTenantEntityAccessError):
            graph.entities_owned_by_tenant("other-corp")


class TestInMemoryEntityGraphStore:
    def test_put_then_get_round_trips(self) -> None:
        store = InMemoryEntityGraphStore()
        graph = build_entity_graph(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=_groups(),
            provenance_ref=_PROVENANCE_REF,
        )
        store.put("acme-corp", "proj-1", graph)
        assert store.get("acme-corp", "proj-1") is graph

    def test_put_rejects_tenant_mismatch(self) -> None:
        store = InMemoryEntityGraphStore()
        graph = build_entity_graph(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=_groups(),
            provenance_ref=_PROVENANCE_REF,
        )
        with pytest.raises(CrossTenantEntityAccessError):
            store.put("other-corp", "proj-1", graph)

    def test_put_rejects_project_mismatch(self) -> None:
        store = InMemoryEntityGraphStore()
        graph = build_entity_graph(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=_groups(),
            provenance_ref=_PROVENANCE_REF,
        )
        with pytest.raises(CrossTenantEntityAccessError):
            store.put("acme-corp", "proj-OTHER", graph)

    def test_get_for_unknown_project_raises_not_found(self) -> None:
        store = InMemoryEntityGraphStore()
        with pytest.raises(EntityGraphNotFoundError):
            store.get("acme-corp", "proj-does-not-exist")

    def test_cross_tenant_query_never_returns_other_tenants_data(self) -> None:
        """Explicit adversarial test (w4-03 hard constraint): an entity
        query for tenant A must never return tenant B's data."""
        store = InMemoryEntityGraphStore()
        graph_a = build_entity_graph(
            tenant_id="tenant-a",
            project_id="proj-1",
            alias_groups=_groups(),
            provenance_ref=_PROVENANCE_REF,
        )
        graph_b = build_entity_graph(
            tenant_id="tenant-b",
            project_id="proj-1",
            alias_groups=_groups(),
            provenance_ref=_PROVENANCE_REF,
        )
        store.put("tenant-a", "proj-1", graph_a)
        store.put("tenant-b", "proj-1", graph_b)

        # Tenant A can only ever read its own graph, never tenant B's, even
        # though both use the identical project_id key.
        fetched = store.get("tenant-a", "proj-1")
        assert fetched.tenant_id == "tenant-a"
        assert fetched is graph_a
        assert fetched is not graph_b

    def test_cross_tenant_existence_is_not_leaked(self) -> None:
        """A tenant probing another tenant's project_id gets the identical
        `EntityGraphNotFoundError` whether or not that project_id exists
        under a different tenant — no side channel distinguishes the two
        cases (never leak cross-tenant existence)."""
        store = InMemoryEntityGraphStore()
        graph_b = build_entity_graph(
            tenant_id="tenant-b",
            project_id="secret-project",
            alias_groups=_groups(),
            provenance_ref=_PROVENANCE_REF,
        )
        store.put("tenant-b", "secret-project", graph_b)

        with pytest.raises(EntityGraphNotFoundError) as exists_elsewhere:
            store.get("tenant-a", "secret-project")
        with pytest.raises(EntityGraphNotFoundError) as never_existed:
            store.get("tenant-a", "totally-unknown-project")

        assert type(exists_elsewhere.value) is type(never_existed.value)

    def test_store_is_isolated_per_tenant_namespace(self) -> None:
        store = InMemoryEntityGraphStore()
        graph_a1 = build_entity_graph(
            tenant_id="tenant-a",
            project_id="proj-1",
            alias_groups=_groups(),
            provenance_ref=_PROVENANCE_REF,
        )
        store.put("tenant-a", "proj-1", graph_a1)
        # A second tenant may reuse the identical project_id without
        # colliding with tenant-a's stored graph.
        with pytest.raises(EntityGraphNotFoundError):
            store.get("tenant-b", "proj-1")

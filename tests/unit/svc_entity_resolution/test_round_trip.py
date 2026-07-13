"""Unit test: full build -> store -> retrieve -> emit round trip, plus a
top-level `saena_entity_resolution` package re-export smoke test."""

from __future__ import annotations

import pytest
import saena_entity_resolution as m

_PROVENANCE_REF = "sha256:" + "e" * 64


def test_public_api_surface_matches_all() -> None:
    for name in m.__all__:
        assert hasattr(m, name), name


def test_full_round_trip_build_store_retrieve_emit() -> None:
    groups = (
        m.AliasGroup(
            entity_id="e1",
            entity_type=m.EntityType.brand,
            canonical_name="Acme",
            aliases=("acme", "Acme Inc"),
            is_owned=True,
        ),
        m.AliasGroup(
            entity_id="e2",
            entity_type=m.EntityType.competitor,
            canonical_name="Rival",
            aliases=("rival",),
            is_owned=False,
        ),
    )

    graph = m.build_entity_graph(
        tenant_id="acme-corp",
        project_id="proj-1",
        alias_groups=groups,
        provenance_ref=_PROVENANCE_REF,
    )

    store = m.InMemoryEntityGraphStore()
    store.put("acme-corp", "proj-1", graph)
    fetched = store.get("acme-corp", "proj-1")
    assert fetched is graph

    envelope = m.build_entity_graph_versioned_envelope(
        fetched, run_id="run-1", idempotency_key="acme-corp:proj-1:v1"
    )
    assert envelope["payload"]["entity_count"] == 2
    assert envelope["payload"]["provenance_ref"] == _PROVENANCE_REF

    # Recomputing from the same alias_groups input must reproduce the exact
    # same graph_version (end-to-end determinism, not just at the
    # canonicalize-module level).
    assert m.recompute_graph_version(graph, groups) == graph.graph_version


def test_cross_tenant_store_query_denied_end_to_end() -> None:
    groups = (
        m.AliasGroup(
            entity_id="e1",
            entity_type=m.EntityType.brand,
            canonical_name="Acme",
            aliases=("acme",),
            is_owned=True,
        ),
    )
    graph = m.build_entity_graph(
        tenant_id="tenant-a",
        project_id="proj-1",
        alias_groups=groups,
        provenance_ref=_PROVENANCE_REF,
    )
    store = m.InMemoryEntityGraphStore()
    store.put("tenant-a", "proj-1", graph)

    with pytest.raises(m.EntityGraphNotFoundError):
        store.get("tenant-b", "proj-1")


def test_competitor_ownership_denied_end_to_end() -> None:
    groups = (
        m.AliasGroup(
            entity_id="e1",
            entity_type=m.EntityType.competitor,
            canonical_name="Rival",
            aliases=("rival",),
            is_owned=True,
        ),
    )
    with pytest.raises(m.CompetitorOwnershipDeniedError):
        m.build_entity_graph(
            tenant_id="acme-corp",
            project_id="proj-1",
            alias_groups=groups,
            provenance_ref=_PROVENANCE_REF,
        )

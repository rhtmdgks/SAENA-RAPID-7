"""`InMemoryDemandGraphStore` tenant-scoping / cross-tenant default-DENY
branches."""

from __future__ import annotations

import pytest
from demand_graph_factories import make_materials_for_all_intents
from saena_demand_graph.builder import build_demand_graph
from saena_demand_graph.errors import CrossTenantDemandGraphError, DemandGraphNotFoundError
from saena_demand_graph.store import InMemoryDemandGraphStore


def _build_graph(tenant_id: str = "acme-inc", project_id: str = "proj-1"):
    materials = make_materials_for_all_intents()
    return build_demand_graph(tenant_id=tenant_id, project_id=project_id, materials=materials)


def test_put_then_get_round_trips() -> None:
    store = InMemoryDemandGraphStore()
    graph = _build_graph()
    store.put("acme-inc", "proj-1", graph)
    fetched = store.get("acme-inc", "proj-1")
    assert fetched == graph


def test_put_rejects_mismatched_tenant_id() -> None:
    store = InMemoryDemandGraphStore()
    graph = _build_graph(tenant_id="acme-inc")
    with pytest.raises(CrossTenantDemandGraphError):
        store.put("other-tenant", "proj-1", graph)


def test_put_rejects_mismatched_project_id() -> None:
    store = InMemoryDemandGraphStore()
    graph = _build_graph(tenant_id="acme-inc", project_id="proj-1")
    with pytest.raises(CrossTenantDemandGraphError):
        store.put("acme-inc", "other-project", graph)


def test_get_unknown_project_raises_not_found() -> None:
    store = InMemoryDemandGraphStore()
    with pytest.raises(DemandGraphNotFoundError):
        store.get("acme-inc", "does-not-exist")


def test_get_stored_under_different_tenant_is_not_found_not_leaked() -> None:
    """Cross-tenant existence must never leak — a graph stored under
    tenant A is indistinguishable from "never stored" to tenant B's read."""
    store = InMemoryDemandGraphStore()
    graph = _build_graph(tenant_id="tenant-a", project_id="proj-1")
    store.put("tenant-a", "proj-1", graph)
    with pytest.raises(DemandGraphNotFoundError):
        store.get("tenant-b", "proj-1")


def test_two_tenants_can_store_same_project_id_independently() -> None:
    store = InMemoryDemandGraphStore()
    graph_a = _build_graph(tenant_id="tenant-a", project_id="proj-1")
    graph_b = _build_graph(tenant_id="tenant-b", project_id="proj-1")
    store.put("tenant-a", "proj-1", graph_a)
    store.put("tenant-b", "proj-1", graph_b)
    assert store.get("tenant-a", "proj-1") == graph_a
    assert store.get("tenant-b", "proj-1") == graph_b

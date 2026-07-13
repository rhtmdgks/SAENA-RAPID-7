"""`InMemoryDemandGraphStore` — tenant-scoped, in-memory `DemandGraph` store.

Mirrors `saena_site_discovery.store.InMemorySiteInventoryStore`'s tenant-gate
discipline exactly: `get`/`put` both take an explicit `tenant_id` argument
which MUST match the stored/storing `DemandGraph.tenant_id`, and a mismatch
on EITHER path raises `CrossTenantDemandGraphError` rather than a bare "not
found" that would let a caller distinguish "wrong tenant" from "never
existed" (tenant-isolation default-DENY, mission constraint). This is a
reference in-memory adapter for this unit's own tests only — a real
persistence adapter (following `saena_domain.persistence`'s port shape) is
out of this patch unit's scope.
"""

from __future__ import annotations

import threading

from saena_demand_graph.errors import CrossTenantDemandGraphError, DemandGraphNotFoundError
from saena_demand_graph.records import DemandGraph


class InMemoryDemandGraphStore:
    """Pure-Python, tenant-scoped `DemandGraph` store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, dict[str, DemandGraph]] = {}

    def put(self, tenant_id: str, project_id: str, graph: DemandGraph) -> DemandGraph:
        """Store `graph` under `(tenant_id, project_id)`.

        Raises `CrossTenantDemandGraphError` if `graph.tenant_id !=
        tenant_id` — a caller cannot store a graph under a tenant it was not
        actually built for.
        """
        if graph.tenant_id != tenant_id:
            raise CrossTenantDemandGraphError(
                "graph.tenant_id does not match the storing tenant_id",
                context={"requested_tenant_id": tenant_id, "graph_tenant_id": graph.tenant_id},
            )
        if graph.project_id != project_id:
            raise CrossTenantDemandGraphError(
                "graph.project_id does not match the storing project_id",
                context={"requested_project_id": project_id, "graph_project_id": graph.project_id},
            )
        with self._lock:
            self._store.setdefault(tenant_id, {})[project_id] = graph
        return graph

    def get(self, tenant_id: str, project_id: str) -> DemandGraph:
        """Return the stored graph for `(tenant_id, project_id)`.

        Raises `DemandGraphNotFoundError` if nothing is stored under that
        exact tenant — a stored graph under a DIFFERENT tenant is
        indistinguishable from "never stored" to this caller, by design
        (never leak cross-tenant existence).
        """
        with self._lock:
            tenant_store = self._store.get(tenant_id, {})
            graph = tenant_store.get(project_id)
        if graph is None:
            raise DemandGraphNotFoundError(
                "no demand graph stored for this tenant/project_id",
                context={"requested_tenant_id": tenant_id, "project_id": project_id},
            )
        return graph


__all__ = ["InMemoryDemandGraphStore"]

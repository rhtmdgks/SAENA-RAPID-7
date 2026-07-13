"""`InMemoryEntityGraphStore` — tenant-scoped, in-memory `EntityGraph` store.

Mirrors `saena_site_discovery.store.InMemorySiteInventoryStore`'s tenant-gate
discipline exactly: `get`/`put` both take an explicit `tenant_id` argument
which MUST match the stored/storing `EntityGraph.tenant_id`, and a mismatch
on EITHER path raises `CrossTenantEntityAccessError` rather than a bare
"not found" that would let a caller distinguish "wrong tenant" from "never
existed" (default-DENY cross-tenant access, w4-03 hard constraint). This is
a reference in-memory adapter for this unit's own tests only — a real
persistence adapter (SQL, following `saena_domain.persistence`'s port shape)
is out of this patch unit's scope.
"""

from __future__ import annotations

import threading

from saena_entity_resolution.errors import CrossTenantEntityAccessError, EntityGraphNotFoundError
from saena_entity_resolution.graph import EntityGraph


class InMemoryEntityGraphStore:
    """Pure-Python, tenant-scoped `EntityGraph` store, keyed by
    `(tenant_id, project_id)`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, dict[str, EntityGraph]] = {}

    def put(self, tenant_id: str, project_id: str, graph: EntityGraph) -> EntityGraph:
        """Store `graph` under `(tenant_id, project_id)`.

        Raises `CrossTenantEntityAccessError` if `graph.tenant_id !=
        tenant_id` — a caller cannot store a graph under a tenant it was
        not actually resolved for.
        """
        if graph.tenant_id != tenant_id:
            raise CrossTenantEntityAccessError(
                "graph.tenant_id does not match the storing tenant_id",
                context={"requested_tenant_id": tenant_id, "graph_tenant_id": graph.tenant_id},
            )
        if graph.project_id != project_id:
            raise CrossTenantEntityAccessError(
                "graph.project_id does not match the storing project_id",
                context={"requested_project_id": project_id, "graph_project_id": graph.project_id},
            )
        with self._lock:
            self._store.setdefault(tenant_id, {})[project_id] = graph
        return graph

    def get(self, tenant_id: str, project_id: str) -> EntityGraph:
        """Return the stored graph for `(tenant_id, project_id)`.

        Raises `EntityGraphNotFoundError` if nothing is stored under that
        exact tenant — a graph stored under a DIFFERENT tenant is
        indistinguishable from "never stored" to this caller, by design
        (never leak cross-tenant existence — an attacker probing tenant B's
        project_ids from tenant A's context gets the identical
        `EntityGraphNotFoundError` whether the project genuinely doesn't
        exist or exists only under a different tenant).
        """
        with self._lock:
            tenant_store = self._store.get(tenant_id, {})
            graph = tenant_store.get(project_id)
        if graph is None:
            raise EntityGraphNotFoundError(
                "no entity graph stored for this tenant/project_id",
                context={"requested_tenant_id": tenant_id, "project_id": project_id},
            )
        return graph


__all__ = ["InMemoryEntityGraphStore"]

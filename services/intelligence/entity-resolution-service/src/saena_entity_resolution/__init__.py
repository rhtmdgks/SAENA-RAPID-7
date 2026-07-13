"""saena_entity_resolution — entity-resolution-service (W4, w4-03).

Tenant-scoped brand/product/integration/competitor alias canonicalization:
merges alias sets into a single canonical `EntityRecord`
(`saena_schemas.domain.entity_record_v1.EntityRecord`) per entity, computes a
deterministic `graph_version` hash for the whole resolved graph (reusing
`saena_domain.audit.canonical` — no new hashing rule), and builds the
`entity.graph.versioned.v1` event payload/envelope for a completed graph
build.

**Ownership rule (fail-closed)**: a `competitor` entity can never be marked
`is_owned=True` — `canonicalize.resolve_entities` raises
`CompetitorOwnershipDeniedError` unconditionally, with no opt-out.

**Tenant scoping**: every domain object carries `tenant_id`;
`store.InMemoryEntityGraphStore` and `graph.EntityGraph.
entities_owned_by_tenant` both raise `CrossTenantEntityAccessError` on any
cross-tenant read/write attempt (default-DENY).

Out of this patch unit's scope (W4 or later, deliberately not implemented
here): a real persistence adapter (SQL/ClickHouse/vector), consumption of
`demand.graph.versioned.v1` as an upstream trigger, any
scoring/recommendation/learning over the resolved graph, a k3s Deployment
manifest or Dockerfile.

Public API:
    AliasGroup / EntityType / EntityResolutionResult / compute_graph_version
        / resolve_entities
    EntityGraph / build_entity_graph / recompute_graph_version
    InMemoryEntityGraphStore
    build_entity_graph_versioned_payload / build_entity_graph_versioned_envelope
        / EntityGraphEventValidationError
    Every error in `errors.py`
"""

from __future__ import annotations

from saena_entity_resolution.canonicalize import (
    AliasGroup,
    EntityResolutionResult,
    EntityType,
    compute_graph_version,
    resolve_entities,
)
from saena_entity_resolution.errors import (
    AliasConflictError,
    CompetitorOwnershipDeniedError,
    CrossTenantEntityAccessError,
    EmptyAliasSetError,
    EntityGraphNotFoundError,
    EntityResolutionError,
)
from saena_entity_resolution.events import (
    EntityGraphEventValidationError,
    build_entity_graph_versioned_envelope,
    build_entity_graph_versioned_payload,
)
from saena_entity_resolution.graph import EntityGraph, build_entity_graph, recompute_graph_version
from saena_entity_resolution.store import InMemoryEntityGraphStore

__all__ = [
    "AliasConflictError",
    "AliasGroup",
    "CompetitorOwnershipDeniedError",
    "CrossTenantEntityAccessError",
    "EmptyAliasSetError",
    "EntityGraph",
    "EntityGraphEventValidationError",
    "EntityGraphNotFoundError",
    "EntityResolutionError",
    "EntityResolutionResult",
    "EntityType",
    "InMemoryEntityGraphStore",
    "build_entity_graph",
    "build_entity_graph_versioned_envelope",
    "build_entity_graph_versioned_payload",
    "compute_graph_version",
    "recompute_graph_version",
    "resolve_entities",
]

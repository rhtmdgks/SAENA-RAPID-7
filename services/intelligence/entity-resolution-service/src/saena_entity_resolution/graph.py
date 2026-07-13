"""`EntityGraph` — the resolved, storable projection of one `(tenant_id,
project_id)` entity-resolution run (w4-03).

Wraps `canonicalize.EntityResolutionResult` with the fields a caller needs to
persist/replay a graph build: the resolved `EntityRecord` tuple, the
deterministic `graph_version`, and a `provenance_ref` (content hash anchoring
this build, mirroring `repo.intaken.v1.content_hash` /
`demand.graph.versioned.v1.provenance_ref`'s existing "hash anchors the
build" convention rather than inventing a new one).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from saena_schemas.domain.entity_record_v1 import EntityRecord

from saena_entity_resolution.canonicalize import (
    AliasGroup,
    compute_graph_version,
    resolve_entities,
)
from saena_entity_resolution.errors import CrossTenantEntityAccessError


def _default_clock() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class EntityGraph:
    """One immutable, tenant/project-scoped resolved entity graph build."""

    tenant_id: str
    project_id: str
    graph_version: str
    provenance_ref: str
    entities: tuple[EntityRecord, ...]

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    def entities_owned_by_tenant(self, tenant_id: str) -> tuple[EntityRecord, ...]:
        """Return this graph's entities IF `tenant_id` matches
        `self.tenant_id`; raises `CrossTenantEntityAccessError` otherwise
        (fail closed — never silently return an empty tuple, which would be
        indistinguishable from "this tenant legitimately has zero
        entities")."""
        if tenant_id != self.tenant_id:
            raise CrossTenantEntityAccessError(
                "requested tenant_id does not match this graph's owning tenant_id",
                context={"requested_tenant_id": tenant_id, "graph_tenant_id": self.tenant_id},
            )
        return self.entities


def build_entity_graph(
    *,
    tenant_id: str,
    project_id: str,
    alias_groups: tuple[AliasGroup, ...],
    provenance_ref: str,
    clock: Callable[[], str] = _default_clock,
) -> EntityGraph:
    """Resolve `alias_groups` (via `canonicalize.resolve_entities`) into an
    `EntityGraph`. `provenance_ref` is caller-supplied — this module does not
    invent how the caller derives their build-provenance hash (e.g. a source
    snapshot hash, an upstream `demand.graph.versioned.v1.graph_version`, or
    `saena_domain.audit.canonical.sha256_hex` over the raw alias input); it
    only requires the `sha256:<hex>` wire form the event contract's
    `provenance_ref` ($ref `sha256_ref`) expects — validated at event-build
    time in `events.py`, not re-validated here (this dataclass itself is not
    contract-bound).

    `clock` is forwarded to `resolve_entities` (test-only determinism hook —
    see that function's own `clock` parameter docstring); defaults to real
    UTC now.
    """
    result = resolve_entities(
        tenant_id=tenant_id,
        project_id=project_id,
        alias_groups=alias_groups,
        clock=clock,
    )
    return EntityGraph(
        tenant_id=result.tenant_id,
        project_id=result.project_id,
        graph_version=result.graph_version,
        provenance_ref=provenance_ref,
        entities=result.entities,
    )


def recompute_graph_version(graph: EntityGraph, alias_groups: tuple[AliasGroup, ...]) -> str:
    """Recompute the `graph_version` hash `alias_groups` would produce for
    `graph.tenant_id`/`graph.project_id`, WITHOUT rebuilding the graph —
    used by integrity checks/tests to confirm "identical input ->
    byte-identical `graph_version`" without a second full
    `build_entity_graph` call."""
    return compute_graph_version(graph.tenant_id, graph.project_id, alias_groups)


__all__ = [
    "EntityGraph",
    "build_entity_graph",
    "recompute_graph_version",
]

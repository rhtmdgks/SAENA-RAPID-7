"""Vector record model — pure data, NO I/O (w4-07).

Spec basis: `docs/decisions/ADR-0007-final-synthesis-ownership-topology.md`
§4-5 rev.2 ("Vector = 제품별 collection·namespace 결정"), `docs/architecture/
data-ownership.md` row 28 ("Qdrant/pgvector | retrieval | tenant partition |
demand-graph/claim-evidence/entity-resolution 소유 파티션 분리"),
`docs/architecture/tenancy-model.md` (tenant_id = hard isolation boundary).

Every `VectorRecord` carries:

- `tenant_id` + `collection` — the per-tenant, per-product partition key
  (ADR-0007 rev.2: tenant partition is the physical isolation axis, product
  ("collection") is the namespacing axis — `collection_key()` below
  combines both into one deterministic physical namespace string, so a
  concrete backend can use it directly as a Qdrant collection name or a
  pgvector partition/filter value without re-deriving the rule itself).
- `embedding` (`EmbeddingMeta`) — model/version/dimension, recorded
  alongside the vector so a caller can always tell which embedding space a
  stored vector belongs to (embedding provider/model choice is OPEN per the
  w4-07 task brief — this package never hardcodes one; see
  `saena_vector_store.embedder.TestEmbedder` for the only concrete embedder
  this package ships, deterministic/offline for tests).
- `source_snapshot_hash` — the provenance link back to the source content
  snapshot (artifact-registry content hash convention,
  `docs/architecture/data-ownership.md` "content hash + lifecycle") this
  vector was derived from. When the snapshot changes, the OLD vector is
  superseded (`superseded`/`superseded_by_hash`) rather than silently
  overwritten in place — see `VectorStore.upsert`/`invalidate_snapshot`
  docstrings (`port.py`) for the exact stale-invalidation semantics.

`VectorRecord` is immutable (`frozen=True, slots=True`) — no backend ever
mutates a stored record in place; every state transition (e.g. superseding
an old version) produces a NEW `VectorRecord` via `dataclasses.replace`.
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_vector_store.errors import DimensionMismatchError, TenantIsolationError


@dataclass(frozen=True, slots=True)
class EmbeddingMeta:
    """Embedding provenance: which model/version produced a vector, and its
    declared dimension.

    Embedding PROVIDER selection itself is OPEN (w4-07 task brief) — this
    package records whatever `model`/`version` string a caller supplies (a
    production embedder is out of this package's scope; only
    `embedder.TestEmbedder`, a deterministic/offline stand-in, ships here).
    """

    model: str
    version: str
    dimension: int

    def __post_init__(self) -> None:
        if self.dimension <= 0:
            raise DimensionMismatchError(
                f"embedding dimension must be a positive integer, got {self.dimension!r}",
                context={"model": self.model, "version": self.version, "dimension": self.dimension},
            )


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """One stored vector, tenant- and collection-scoped, with embedding
    provenance and source-snapshot lineage.

    `__post_init__` enforces the dimension invariant unconditionally and
    fail-closed (`DimensionMismatchError`) — there is no way to construct a
    `VectorRecord` whose `vector` length disagrees with its own
    `embedding.dimension`; this is checked BEFORE the object exists, not
    after the fact by a caller remembering to validate it.
    """

    tenant_id: str
    collection: str
    record_id: str
    vector: tuple[float, ...]
    embedding: EmbeddingMeta
    source_snapshot_hash: str
    superseded: bool = False
    superseded_by_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id must be a non-empty string")
        if not self.collection:
            raise ValueError("collection must be a non-empty string")
        if not self.record_id:
            raise ValueError("record_id must be a non-empty string")
        if not self.source_snapshot_hash:
            raise ValueError("source_snapshot_hash must be a non-empty string (provenance link)")
        if len(self.vector) != self.embedding.dimension:
            raise DimensionMismatchError(
                f"vector has {len(self.vector)} component(s) but embedding metadata "
                f"declares dimension={self.embedding.dimension}",
                context={
                    "tenant_id": self.tenant_id,
                    "collection": self.collection,
                    "record_id": self.record_id,
                    "actual_dimension": len(self.vector),
                    "declared_dimension": self.embedding.dimension,
                },
            )


def collection_key(tenant_id: str, collection: str) -> str:
    """Deterministic per-tenant, per-product physical namespace key.

    ADR-0007 rev.2 authorizes a PER-PRODUCT collection/namespace decision
    ("Vector = 제품별 collection·namespace 결정") layered on top of the
    blanket tenant-partition rule (`data-ownership.md` row 28) — this
    function is the single, canonical combination of both axes so every
    backend derives the same physical name from the same two logical
    fields, whether that name becomes a Qdrant collection name or a
    pgvector `(tenant_id, collection)` filter pair.
    """
    if not tenant_id or not collection:
        raise ValueError("tenant_id and collection must both be non-empty strings")
    return f"{collection}__{tenant_id}"


def ensure_caller_owns_record(tenant_id: str, record: VectorRecord) -> None:
    """Fail closed if `record.tenant_id` does not match the caller-supplied
    `tenant_id` — the shared "forged tenant id" guard every `VectorStore`
    backend calls BEFORE any I/O, so a forged record can never reach
    storage under either the claimed or the forging tenant.
    """
    if record.tenant_id != tenant_id:
        raise TenantIsolationError(
            "record.tenant_id does not match the caller-supplied tenant_id — refusing "
            "to store/return a record across a tenant boundary",
            context={"caller_tenant_id": tenant_id, "record_tenant_id": record.tenant_id},
        )


__all__ = [
    "EmbeddingMeta",
    "VectorRecord",
    "collection_key",
    "ensure_caller_owns_record",
]

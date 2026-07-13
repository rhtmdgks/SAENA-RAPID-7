"""`InMemoryVectorStore` — pure-Python reference `VectorStore` (w4-07).

No SQL, no network I/O — used by this package's own deterministic unit
tests (`tests/unit/vector_store/**`) and by any caller that does not yet
need a real backend. Reproduces `PgVectorStore`'s (`pgvector/adapter.py`)
behavior exactly: same tenant-isolation checks, same idempotent-replay /
stale-invalidation rules, same dimension-mismatch fail-closed behavior —
see each method's docstring for the `PgVectorStore` counterpart it mirrors.

Tenant isolation (structural, not conventional): every stored version is
keyed by a tuple that STARTS with `tenant_id` — `(tenant_id, collection,
record_id)` — so a lookup under a different `tenant_id` is a different dict
key entirely; there is no way for one tenant's lookup to observe another
tenant's stored data by construction, independent of any `if` check. The
EXTRA `record.tenant_id == tenant_id` check in `upsert` (via
`ensure_caller_owns_record`) exists on top of that for the one case the key
alone cannot catch: a caller passing a truthful `tenant_id` positional
argument alongside a RECORD object whose own embedded `tenant_id` field
claims a different tenant (the "forged tenant id" attack this port's
`upsert` docstring names) — the key-based structural isolation still
applies (the forged record is rejected before any key is ever written
under either tenant), this check is what produces the actionable
`TenantIsolationError` instead of a confusing silent success under the
wrong key.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import replace

from saena_vector_store.errors import DimensionMismatchError, NotFoundError
from saena_vector_store.port import VectorSearchHit
from saena_vector_store.record import VectorRecord, ensure_caller_owns_record

_Key = tuple[str, str, str]  # (tenant_id, collection, record_id)
_DimKey = tuple[str, str]  # (tenant_id, collection)


def _l2_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Plain Euclidean (L2) distance — pure `math`, no `numpy` dependency
    (matches `PgVectorStore`'s use of pgvector's native `<->` L2 operator,
    so in-memory and real-backend ANN ordering agree for the same inputs)."""
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


class InMemoryVectorStore:
    """Reference `VectorStore` — one version-history list per
    `(tenant_id, collection, record_id)`, guarded by a single `threading.Lock`
    (mirrors `saena_domain.persistence.memory`'s in-memory adapters'
    locking convention).

    Methods are declared `async def` to genuinely satisfy `port.VectorStore`
    (an async Protocol — see `port.py`'s module docstring for why) even
    though no actual I/O occurs; each method's body is synchronous
    lock-protected dict manipulation.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._versions: dict[_Key, list[VectorRecord]] = {}
        self._dimensions: dict[_DimKey, int] = {}

    async def upsert(
        self, tenant_id: str, records: Sequence[VectorRecord]
    ) -> tuple[VectorRecord, ...]:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        results: list[VectorRecord] = []
        with self._lock:
            for record in records:
                ensure_caller_owns_record(tenant_id, record)
                dim_key: _DimKey = (tenant_id, record.collection)
                established = self._dimensions.get(dim_key)
                if established is not None and established != record.embedding.dimension:
                    raise DimensionMismatchError(
                        f"collection {record.collection!r} for tenant {tenant_id!r} is "
                        f"established at dimension={established}, got "
                        f"dimension={record.embedding.dimension}",
                        context={
                            "tenant_id": tenant_id,
                            "collection": record.collection,
                            "record_id": record.record_id,
                            "established_dimension": established,
                            "incoming_dimension": record.embedding.dimension,
                        },
                    )

                key: _Key = (tenant_id, record.collection, record.record_id)
                history = self._versions.setdefault(key, [])
                if history and not history[-1].superseded:
                    active = history[-1]
                    if active.source_snapshot_hash == record.source_snapshot_hash:
                        # Idempotent replay — no-op, return the stored active
                        # record unchanged (same convention as
                        # `PlanRepository.put_plan`).
                        results.append(active)
                        continue
                    # Stale invalidation: the source snapshot changed, so the
                    # previously-active version is superseded (never deleted).
                    history[-1] = replace(
                        active, superseded=True, superseded_by_hash=record.source_snapshot_hash
                    )

                new_active = replace(record, superseded=False, superseded_by_hash=None)
                history.append(new_active)
                self._dimensions[dim_key] = record.embedding.dimension
                results.append(new_active)
        return tuple(results)

    async def search(
        self, tenant_id: str, collection: str, query_vector: Sequence[float], k: int
    ) -> tuple[VectorSearchHit, ...]:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if k <= 0:
            raise ValueError(f"k must be a positive integer, got {k!r}")
        with self._lock:
            established = self._dimensions.get((tenant_id, collection))
            if established is not None and len(query_vector) != established:
                raise DimensionMismatchError(
                    f"query_vector has {len(query_vector)} component(s) but collection "
                    f"{collection!r} for tenant {tenant_id!r} is established at "
                    f"dimension={established}",
                    context={
                        "tenant_id": tenant_id,
                        "collection": collection,
                        "query_dimension": len(query_vector),
                        "established_dimension": established,
                    },
                )
            candidates = [
                history[-1]
                for (t, c, _rid), history in self._versions.items()
                if t == tenant_id and c == collection and history and not history[-1].superseded
            ]
        scored = [
            VectorSearchHit(record=rec, distance=_l2_distance(query_vector, rec.vector))
            for rec in candidates
        ]
        scored.sort(key=lambda hit: hit.distance)
        return tuple(scored[:k])

    async def get(self, tenant_id: str, collection: str, record_id: str) -> VectorRecord:
        versions = await self.list_versions(tenant_id, collection, record_id)
        if not versions:
            raise NotFoundError(
                f"no vector record for tenant={tenant_id!r} collection={collection!r} "
                f"record_id={record_id!r}",
                context={"tenant_id": tenant_id, "collection": collection, "record_id": record_id},
            )
        return versions[-1]

    async def list_versions(
        self, tenant_id: str, collection: str, record_id: str
    ) -> tuple[VectorRecord, ...]:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        key: _Key = (tenant_id, collection, record_id)
        with self._lock:
            return tuple(self._versions.get(key, []))

    async def delete(self, tenant_id: str, collection: str, record_ids: Sequence[str]) -> int:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        deleted = 0
        with self._lock:
            for record_id in record_ids:
                key: _Key = (tenant_id, collection, record_id)
                if key in self._versions:
                    del self._versions[key]
                    deleted += 1
        return deleted

    async def invalidate_snapshot(
        self,
        tenant_id: str,
        collection: str,
        source_snapshot_hash: str,
        *,
        superseded_by_hash: str | None = None,
    ) -> tuple[VectorRecord, ...]:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        updated: list[VectorRecord] = []
        with self._lock:
            for (t, c, _rid), history in self._versions.items():
                if t != tenant_id or c != collection or not history:
                    continue
                active = history[-1]
                if active.superseded or active.source_snapshot_hash != source_snapshot_hash:
                    continue
                new_active = replace(active, superseded=True, superseded_by_hash=superseded_by_hash)
                history[-1] = new_active
                updated.append(new_active)
        return tuple(updated)


__all__ = ["InMemoryVectorStore"]

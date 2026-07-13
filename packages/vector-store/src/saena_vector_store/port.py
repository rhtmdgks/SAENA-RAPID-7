"""`VectorStore` port — `typing.Protocol` only, NO I/O (w4-07).

Spec basis: ADR-0007 §4-5 rev.2, `docs/architecture/data-ownership.md` row
28, `docs/architecture/tenancy-model.md`. Mirrors the shape of
`saena_domain.persistence.ports` (this repo's existing persistence-port
convention: `typing.Protocol`, `tenant_id` as the mandatory first argument
of every tenant-scoped method) WITHOUT importing it — this package is
deliberately self-contained (see `README.md` "Packaging note").

Async-native, unlike `saena_domain.persistence.ports` (whose Protocol
declares plain `def` while its own Postgres adapters implement `async def`
— an existing, accepted inconsistency in that sibling package this unit
does not touch). The ONE real backend this package ships (`PgVectorStore`,
`pgvector/adapter.py`) is inherently I/O-bound (asyncpg), so the Protocol
itself is declared `async def` throughout and `InMemoryVectorStore`
(`memory.py`) implements the identical async signatures (trivially, since
no actual I/O occurs) — every concrete backend genuinely satisfies the same
Protocol, both structurally (`isinstance` via `@runtime_checkable`) and by
static signature shape.

`tenant_id` IS A REQUIRED FIRST PARAMETER on every method below — there is
no default, no keyword-only escape hatch, and no alternate entry point that
lets a caller upsert/search/delete/get without supplying it. Calling any of
these methods without `tenant_id` is a plain Python `TypeError` (missing
required positional argument) BEFORE the method body ever runs — see
`tests/unit/vector_store/test_tenant_required_api.py` for the structural
proof, checked by signature introspection against BOTH concrete backends.
Every concrete implementation injects `tenant_id` INSIDE its own storage
key / SQL `WHERE` clause — never as a post-hoc filter layered over an
already tenant-unaware result set — so a cross-tenant leak is structurally
impossible, not just conventionally discouraged. See `record.
ensure_caller_owns_record` for the additional "forged tenant id" guard
(`record.tenant_id` disagreeing with the caller-supplied `tenant_id`) every
backend applies before any write.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from saena_vector_store.record import VectorRecord


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    """One ANN search result: the stored record plus its distance to the query vector.

    Lower `distance` = more similar (this package standardizes on Euclidean/
    L2 distance throughout — `InMemoryVectorStore` and `PgVectorStore` both
    use plain L2, `PgVectorStore` via pgvector's native `<->` operator, so
    behavior matches between the reference in-memory backend and the real
    one for deterministic-embedding test fixtures).
    """

    record: VectorRecord
    distance: float


@runtime_checkable
class VectorStore(Protocol):
    """Tenant- and collection-scoped vector store port.

    Every method's tenant filter is applied INSIDE the query/storage
    lookup, never as a post-processing step over an unfiltered result —
    see this module's docstring and each concrete backend's own docstring
    for exactly how.
    """

    async def upsert(
        self, tenant_id: str, records: Sequence[VectorRecord]
    ) -> tuple[VectorRecord, ...]:
        """Insert or supersede each of `records`, keyed by
        `(tenant_id, record.collection, record.record_id)`.

        Every `record.tenant_id` MUST equal `tenant_id` — a mismatch (a
        "forged tenant id") raises `TenantIsolationError` for THAT record
        before any of it is written (see `record.ensure_caller_owns_record`).

        Stale-vector invalidation (source-snapshot-hash driven): if an
        ACTIVE record already exists for a given key —

        - same `source_snapshot_hash` as the incoming record: idempotent
          replay, a no-op — the ALREADY-STORED active record is returned
          unchanged (mirrors this repo's existing idempotent-upsert
          convention, e.g. `saena_domain.persistence.ports.PlanRepository.
          put_plan`).
        - a DIFFERENT `source_snapshot_hash`: the old active record is
          marked `superseded=True`/`superseded_by_hash=<new hash>` (never
          deleted — full version history is retrievable via
          `list_versions`) and the new record becomes the active version.

        A dimension mismatch against the dimension already ESTABLISHED for
        `(tenant_id, collection)` by an earlier upsert raises
        `DimensionMismatchError` and rejects that record outright (no
        partial write for that record).
        """
        ...

    async def search(
        self, tenant_id: str, collection: str, query_vector: Sequence[float], k: int
    ) -> tuple[VectorSearchHit, ...]:
        """Return up to `k` nearest ACTIVE (non-superseded) vectors to
        `query_vector`, restricted to `tenant_id`'s own `collection`.

        The `tenant_id` restriction is a structural part of the
        query/storage lookup itself (a SQL `WHERE tenant_id = ...` clause
        for `PgVectorStore`, a dict key component for `InMemoryVectorStore`)
        — a numerically nearer vector belonging to a DIFFERENT tenant is
        never a candidate in the first place, so it can never leak into the
        result regardless of distance (the cross-tenant NN-leakage negative
        test, `tests/integration/vector/test_pgvector_store.py`, proves
        this against a real Postgres/pgvector backend).

        Raises `DimensionMismatchError` if `len(query_vector)` disagrees
        with the dimension established for `(tenant_id, collection)`.
        Raises `ValueError` if `k <= 0`.
        """
        ...

    async def get(self, tenant_id: str, collection: str, record_id: str) -> VectorRecord:
        """Return the CURRENT (latest, possibly `superseded`) version of the
        record for `(tenant_id, collection, record_id)`.

        Raises `NotFoundError` if no version has ever been upserted for
        this key under this `tenant_id` (a record that exists ONLY under a
        different tenant raises `NotFoundError`, not `TenantIsolationError`
        — there is no way to observe a different tenant's key existing at
        all through this port, structurally, since every lookup is already
        keyed by the caller's own `tenant_id`).
        """
        ...

    async def list_versions(
        self, tenant_id: str, collection: str, record_id: str
    ) -> tuple[VectorRecord, ...]:
        """Return every version ever upserted for
        `(tenant_id, collection, record_id)`, oldest first — empty tuple if
        none. The last element is always the CURRENT version (matches
        `get`'s return value); every earlier element has
        `superseded=True`."""
        ...

    async def delete(self, tenant_id: str, collection: str, record_ids: Sequence[str]) -> int:
        """Permanently delete every version of each id in `record_ids` for
        `(tenant_id, collection)`. Returns the count of ids that had at
        least one version deleted (ids with no stored version are silently
        skipped, not an error). Never touches another tenant's record even
        if `record_ids` collides with an id that exists under a different
        tenant — the deletion key always includes `tenant_id`."""
        ...

    async def invalidate_snapshot(
        self,
        tenant_id: str,
        collection: str,
        source_snapshot_hash: str,
        *,
        superseded_by_hash: str | None = None,
    ) -> tuple[VectorRecord, ...]:
        """Mark every ACTIVE record in `(tenant_id, collection)` whose
        `source_snapshot_hash` equals the given hash as `superseded=True`
        (`superseded_by_hash` set to the given value, or `None` if the
        caller does not yet have a replacement vector — e.g. invalidating
        ahead of re-embedding). Returns the updated records. Records already
        `superseded`, or with a different `source_snapshot_hash`, are left
        untouched."""
        ...


__all__ = ["VectorSearchHit", "VectorStore"]

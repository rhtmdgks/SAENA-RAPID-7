"""Exception hierarchy for `saena_vector_store` (w4-07).

Follows the exact same shape as `saena_domain.persistence.errors`
(`saena.<category>.<reason>` `error_code` + structured, log-safe `context`
dict) — this package is intentionally NOT a dependency of `saena_domain`
(exclusive write path is `packages/vector-store/**` only, no root workspace
registration yet, see this package's `README.md`), so the error classes are
a local, small re-derivation of that convention rather than an import of
it, keeping this package fully self-contained.
"""

from __future__ import annotations

from typing import Any


class VectorStoreError(Exception):
    """Base class for every error raised by `saena_vector_store`.

    Attributes:
        error_code: `saena.<category>.<reason>` taxonomy string (mirrors
            ADR-0015's canonical error model), reusable verbatim as a
            services-layer ProblemDetail `error_code`.
        context: structured, log-safe data describing the violation.
    """

    error_code: str = "saena.vector_store.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class TenantIsolationError(VectorStoreError):
    """A caller attempted to read/write/search another tenant's vectors.

    Raised whenever a caller-supplied `tenant_id` does not match either (a)
    the `tenant_id` embedded on a `VectorRecord` being upserted (a "forged
    tenant id" attempt), or (b) the owning tenant of a record a caller is
    trying to read/delete/invalidate. This is the ONE error every backend
    (`InMemoryVectorStore`, `PgVectorStore`) raises for a cross-tenant access
    attempt — never a bare `NotFoundError` or a silently empty result, since
    a cross-tenant access attempt is a security event, not a "not found".
    """

    error_code = "saena.vector_store.tenant_isolation_violation"


class NotFoundError(VectorStoreError):
    """No vector record exists for the given key (within the caller's own tenant)."""

    error_code = "saena.vector_store.not_found"


class DimensionMismatchError(VectorStoreError):
    """A vector's length does not match its declared/established embedding dimension.

    Raised in three structurally distinct places, all fail-closed:

    1. `VectorRecord` construction — `len(vector) != embedding.dimension`
       (pure model-level invariant, `record.py`).
    2. `VectorStore.upsert` — a record's `embedding.dimension` does not
       match the dimension already ESTABLISHED for that
       `(tenant_id, collection)` by an earlier upsert (`memory.py`).
    3. `PgVectorStore` — a real Postgres `vector(N)` column rejects an
       insert/query whose vector literal has a different length; the
       backend's own asyncpg `DataError` is translated to this exception
       (`pgvector/adapter.py`) rather than leaking a raw driver exception.

    A dimension mismatch is NEVER silently truncated, padded, or coerced —
    the record/query is rejected outright.
    """

    error_code = "saena.vector_store.dimension_mismatch"


__all__ = [
    "DimensionMismatchError",
    "NotFoundError",
    "TenantIsolationError",
    "VectorStoreError",
]

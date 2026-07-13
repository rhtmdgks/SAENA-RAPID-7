"""`saena_vector_store` — the `VectorStore` port + its concrete backends (w4-07).

See `README.md` for scope, the pgvector backend-choice rationale, and the
Integrator actions needed to register this package as a `uv` workspace
member.
"""

from __future__ import annotations

from saena_vector_store.embedder import TestEmbedder
from saena_vector_store.errors import (
    DimensionMismatchError,
    NotFoundError,
    TenantIsolationError,
    VectorStoreError,
)
from saena_vector_store.memory import InMemoryVectorStore
from saena_vector_store.port import VectorSearchHit, VectorStore
from saena_vector_store.record import EmbeddingMeta, VectorRecord, collection_key

__all__ = [
    "DimensionMismatchError",
    "EmbeddingMeta",
    "InMemoryVectorStore",
    "NotFoundError",
    "TenantIsolationError",
    "TestEmbedder",
    "VectorRecord",
    "VectorSearchHit",
    "VectorStore",
    "VectorStoreError",
    "collection_key",
]

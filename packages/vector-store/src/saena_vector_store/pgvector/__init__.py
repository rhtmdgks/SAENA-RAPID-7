"""`pgvector` backend for `saena_vector_store` (w4-07) — one concrete
`VectorStore` implementation, chosen for CI cost (reuses the repo's
existing real-Postgres testcontainer, ADR-0017) — NOT a product-wide
standardization. See `saena_vector_store` package `README.md` "Backend
choice" for the OPEN Qdrant-vs-pgvector rationale (Algorithm §398)."""

from __future__ import annotations

from saena_vector_store.pgvector.adapter import PgVectorStore

__all__ = ["PgVectorStore"]

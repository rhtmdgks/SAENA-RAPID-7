"""Raw-SQL DDL for the `PgVectorStore` backend (w4-07).

No committed migration files exist anywhere in this repository yet
(`database/migrations/**` is a protected path this patch unit does not
touch, mirroring `saena_domain.persistence.postgres.tables`'s own "Expand/
contract policy note") — this module is the ONLY schema definition for the
table below, applied test-scoped via `PgVectorStore.create_schema()` inside
`tests/integration/vector/conftest.py`, never against a long-lived database.

Plain raw SQL text (not SQLAlchemy Core `Table`/`Column` objects): the
Postgres `vector` extension type has no built-in SQLAlchemy column type,
and this package deliberately avoids adding the `pgvector` PyPI client
library as a dependency (see `pgvector/adapter.py` module docstring) — a
`sqlalchemy.types.UserDefinedType` subclass would only handle DDL
generation, not asyncpg parameter binding for the extension type, so the
adapter casts vector literals via `CAST(:x AS vector)`/`::text` in raw SQL
instead (see `adapter.py`). Keeping DDL as plain SQL strings here avoids
straddling two different type systems for no benefit.

Own-schema (ADR-0007 "own DB or own schema per service"): `saena_vector` is
this package's own dedicated schema, distinct from
`saena_domain.persistence.postgres.tables.SCHEMA_NAME`
(`saena_persistence`) — this package does not share a schema with any
other patch unit's tables.
"""

from __future__ import annotations

SCHEMA_NAME = "saena_vector"
TABLE_NAME = "vector_records"


def qualified_table() -> str:
    """`"schema"."table"` reference used by every statement in `adapter.py`."""
    return f'"{SCHEMA_NAME}"."{TABLE_NAME}"'


CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS vector"
CREATE_SCHEMA_SQL = f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA_NAME}"'
TRUNCATE_SQL = f"TRUNCATE TABLE {qualified_table()}"


def create_table_sql(dimension: int) -> str:
    """`vector(dimension)` is baked directly into the column type — pgvector
    requires a fixed dimension per column; there is no dimension-agnostic
    column type. `dimension` here is an internal, integer-typed,
    trusted-caller value (never user/tenant-supplied text), so simple
    f-string interpolation into DDL is safe (no SQL injection surface —
    contrast with every DML statement in `adapter.py`, which binds all
    tenant/caller-supplied values as real parameters, never interpolated).
    """
    if dimension <= 0:
        raise ValueError(f"dimension must be a positive integer, got {dimension!r}")
    return f"""
        CREATE TABLE IF NOT EXISTS {qualified_table()} (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            collection TEXT NOT NULL,
            record_id TEXT NOT NULL,
            vector vector({dimension}) NOT NULL,
            embedding_model TEXT NOT NULL,
            embedding_version TEXT NOT NULL,
            embedding_dimension INTEGER NOT NULL,
            source_snapshot_hash TEXT NOT NULL,
            superseded BOOLEAN NOT NULL DEFAULT FALSE,
            superseded_by_hash TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """


def create_index_sql() -> str:
    """B-tree lookup index for the `(tenant_id, collection, record_id)` key
    every adapter method filters/orders by. Deliberately NOT an ANN index
    (e.g. ivfflat/hnsw) — this package's integration tests use tiny
    fixture-sized tables where a full scan + `ORDER BY vector <-> ...` is
    both correct and fast; an approximate-nearest-neighbor index is a
    production tuning concern (index lists/params depend on real corpus
    size) explicitly out of this patch unit's scope."""
    return (
        f"CREATE INDEX IF NOT EXISTS ix_vector_records_lookup ON {qualified_table()} "
        "(tenant_id, collection, record_id)"
    )


__all__ = [
    "CREATE_EXTENSION_SQL",
    "CREATE_SCHEMA_SQL",
    "SCHEMA_NAME",
    "TABLE_NAME",
    "TRUNCATE_SQL",
    "create_index_sql",
    "create_table_sql",
    "qualified_table",
]

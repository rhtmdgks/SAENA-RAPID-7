"""`PgVectorStore` — the ONE concrete `VectorStore` backend this package
ships, over real Postgres + the `pgvector` extension (w4-07).

Backend choice (task brief, authoritative): the Qdrant-vs-pgvector CHOICE is
explicitly OPEN (Algorithm §398) — this package does NOT standardize the
product on pgvector. pgvector is implemented here ONLY because it reuses
this repo's existing real-Postgres testcontainer (ADR-0017,
`tests/integration/persistence_postgres/conftest.py` precedent), which is
the lowest-CI-cost way to prove the `VectorStore` port against a REAL
backend rather than only the in-memory reference (`memory.py`). A Qdrant
adapter is equally authorized behind the same `port.VectorStore` Protocol
whenever a future patch unit needs it (see package `README.md` "Backend
choice").

No `pgvector` PyPI client library dependency: this module talks to Postgres
via plain SQLAlchemy Core (`AsyncEngine`/raw `text()` statements) + asyncpg,
casting vector literals as `CAST(:x AS vector)` / reading them back via
`vector::text` and parsing pgvector's own bracketed-list text format
(`_vector_to_literal`/`_parse_vector_literal` below) — see `pgvector/
tables.py` module docstring for why a SQLAlchemy `UserDefinedType` alone
would not be enough.

Real-Postgres dimension enforcement (`DimensionMismatchError` case 3, see
`errors.py`): this adapter deliberately does NOT re-validate a vector's
length against the table's own established `vector(N)` column width in
Python before sending it to Postgres — the column type itself is the
authority (baked in at `create_schema(engine, dimension=...)` time, see
`pgvector/tables.py`). A mismatched-length CAST is rejected by Postgres
itself with a raw asyncpg `DataError` (observed as `"expected N
dimensions, not M"`); `_translate_dimension_error` below is the ONE place
that catches that raw driver error (wrapped by SQLAlchemy as `DBAPIError`)
and re-raises the package's own `DimensionMismatchError`, on both the
`upsert` and `search` paths — never left to leak a raw driver exception to
a caller. This is a genuine, independent enforcement point from
`VectorRecord.__post_init__`'s own dimension check (`record.py`): that
guards `len(vector) == embedding.dimension` (an internally-consistent
record), this guards the record's declared dimension against the PHYSICAL
table dimension established at schema-creation time (e.g. a caller
re-embedding under a different model whose output dimension does not match
the collection this store instance was built against) — see
`tests/integration/vector/test_pgvector_store.py::
test_upsert_with_wrong_embedding_dimension_is_rejected_by_real_postgres` and
`::test_search_with_wrong_dimension_query_vector_is_rejected_by_real_postgres`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from saena_vector_store.errors import DimensionMismatchError, NotFoundError
from saena_vector_store.pgvector.tables import (
    CREATE_EXTENSION_SQL,
    CREATE_SCHEMA_SQL,
    TRUNCATE_SQL,
    create_index_sql,
    create_table_sql,
    qualified_table,
)
from saena_vector_store.port import VectorSearchHit
from saena_vector_store.record import EmbeddingMeta, VectorRecord, ensure_caller_owns_record

_TABLE = qualified_table()


def _vector_to_literal(vector: Sequence[float]) -> str:
    """pgvector's own bracketed text input format, e.g. `"[1.0,2.0,3.0]"` —
    accepted directly by `CAST(:v AS vector)`."""
    return "[" + ",".join(repr(float(component)) for component in vector) + "]"


def _parse_vector_literal(literal: str) -> tuple[float, ...]:
    """Inverse of `_vector_to_literal` — parses pgvector's `vector::text`
    output (the same bracketed format) back into a plain float tuple."""
    inner = literal.strip().removeprefix("[").removesuffix("]")
    if not inner:
        return ()
    return tuple(float(part) for part in inner.split(","))


def _translate_dimension_error(exc: DBAPIError) -> None:
    """Re-raise `DimensionMismatchError` if `exc` is pgvector's own
    dimension-mismatch `DataError` (observed message shapes: `"expected N
    dimensions, not M"` when casting a wrong-length literal to an
    established `vector(N)` column, `"different vector dimensions N and
    M"` when comparing two differently-sized vector operands directly) —
    both contain the substring `"dimensions"`, which no other pgvector/
    Postgres error this adapter can trigger does. Otherwise re-raises `exc`
    unchanged (never swallows an unrelated database error)."""
    message = str(exc.orig) if exc.orig is not None else str(exc)
    if "dimensions" in message:
        raise DimensionMismatchError(
            "Postgres rejected this vector: its length does not match the "
            "vector(N) column dimension established for this table at "
            "create_schema() time",
            context={"driver_message": message},
        ) from exc
    raise exc


def _row_to_record(row: Sequence[Any]) -> VectorRecord:
    """Build a `VectorRecord` from one raw row of the standard column
    projection every read query below selects, in order (see each query).

    `row` is a SQLAlchemy `Row`/plain tuple — annotated `Sequence[Any]`
    (rather than destructuring straight off an `object`) so mypy can check
    the surrounding call sites without needing a per-line `type: ignore`."""
    (
        tenant_id,
        collection,
        record_id,
        vector_text,
        embedding_model,
        embedding_version,
        embedding_dimension,
        source_snapshot_hash,
        superseded,
        superseded_by_hash,
    ) = row
    return VectorRecord(
        tenant_id=tenant_id,
        collection=collection,
        record_id=record_id,
        vector=_parse_vector_literal(vector_text),
        embedding=EmbeddingMeta(
            model=embedding_model, version=embedding_version, dimension=embedding_dimension
        ),
        source_snapshot_hash=source_snapshot_hash,
        superseded=superseded,
        superseded_by_hash=superseded_by_hash,
    )


_READ_COLUMNS = (
    "tenant_id, collection, record_id, vector::text, embedding_model, "
    "embedding_version, embedding_dimension, source_snapshot_hash, "
    "superseded, superseded_by_hash"
)


class PgVectorStore:
    """`VectorStore` over real Postgres + pgvector — one physical table
    (`pgvector/tables.py`), tenant/collection isolation via `WHERE`-clause
    filters that are always part of the query itself (see `port.py` module
    docstring and this class's own method docstrings for how each query is
    structurally scoped).

    Every method opens (and commits) its own short-lived transaction via
    the bound `AsyncEngine` — no cross-call transactional state, matching
    `InMemoryVectorStore`'s per-call `threading.Lock`-scoped critical
    sections translated to Postgres's own transaction boundary.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @staticmethod
    async def create_schema(engine: AsyncEngine, *, dimension: int) -> None:
        """Test-scoped DDL entry point (see `pgvector/tables.py` module
        docstring — no committed migration exists yet). `dimension` is
        baked into the `vector(dimension)` column type for the WHOLE table;
        every `VectorRecord` upserted through a `PgVectorStore` bound to
        this schema must have been produced by an embedder of this exact
        dimension (see this module's docstring, "Real-Postgres dimension
        enforcement")."""
        async with engine.begin() as conn:
            await conn.execute(text(CREATE_EXTENSION_SQL))
            await conn.execute(text(CREATE_SCHEMA_SQL))
            await conn.execute(text(create_table_sql(dimension)))
            await conn.execute(text(create_index_sql()))

    @staticmethod
    async def truncate(engine: AsyncEngine) -> None:
        """Per-test isolation helper (mirrors `tests/integration/
        persistence_postgres/conftest.py`'s TRUNCATE-between-tests
        convention) — wipes every row without dropping the table/extension."""
        async with engine.begin() as conn:
            await conn.execute(text(TRUNCATE_SQL))

    async def upsert(
        self, tenant_id: str, records: Sequence[VectorRecord]
    ) -> tuple[VectorRecord, ...]:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        results: list[VectorRecord] = []
        async with self._engine.begin() as conn:
            for record in records:
                ensure_caller_owns_record(tenant_id, record)
                results.append(await self._upsert_one(conn, tenant_id, record))
        return tuple(results)

    async def _upsert_one(
        self, conn: AsyncConnection, tenant_id: str, record: VectorRecord
    ) -> VectorRecord:
        # Lock the current active row (if any) for this key so a concurrent
        # upsert against the SAME key inside another transaction cannot
        # interleave between the SELECT and the supersede/insert below.
        active_row = (
            await conn.execute(
                text(
                    f"SELECT id, source_snapshot_hash FROM {_TABLE} "
                    "WHERE tenant_id = :tenant_id AND collection = :collection "
                    "AND record_id = :record_id AND superseded = FALSE "
                    "FOR UPDATE"
                ),
                {
                    "tenant_id": tenant_id,
                    "collection": record.collection,
                    "record_id": record.record_id,
                },
            )
        ).first()

        is_idempotent_replay = (
            active_row is not None
            and active_row.source_snapshot_hash == record.source_snapshot_hash
        )
        if is_idempotent_replay:
            # Idempotent replay — no-op, return the already-stored active
            # record unchanged (mirrors `InMemoryVectorStore.upsert`).
            return await self.get(tenant_id, record.collection, record.record_id)

        if active_row is not None:
            await conn.execute(
                text(
                    f"UPDATE {_TABLE} SET superseded = TRUE, "
                    "superseded_by_hash = :new_hash WHERE id = :id"
                ),
                {"new_hash": record.source_snapshot_hash, "id": active_row.id},
            )

        try:
            await conn.execute(
                text(
                    f"INSERT INTO {_TABLE} "
                    "(tenant_id, collection, record_id, vector, embedding_model, "
                    "embedding_version, embedding_dimension, source_snapshot_hash, "
                    "superseded, superseded_by_hash) "
                    "VALUES (:tenant_id, :collection, :record_id, "
                    "CAST(:vector AS vector), :embedding_model, :embedding_version, "
                    ":embedding_dimension, :source_snapshot_hash, FALSE, NULL)"
                ),
                {
                    "tenant_id": tenant_id,
                    "collection": record.collection,
                    "record_id": record.record_id,
                    "vector": _vector_to_literal(record.vector),
                    "embedding_model": record.embedding.model,
                    "embedding_version": record.embedding.version,
                    "embedding_dimension": record.embedding.dimension,
                    "source_snapshot_hash": record.source_snapshot_hash,
                },
            )
        except DBAPIError as exc:
            _translate_dimension_error(exc)
            raise  # pragma: no cover — _translate_dimension_error always raises
        return VectorRecord(
            tenant_id=tenant_id,
            collection=record.collection,
            record_id=record.record_id,
            vector=record.vector,
            embedding=record.embedding,
            source_snapshot_hash=record.source_snapshot_hash,
            superseded=False,
            superseded_by_hash=None,
        )

    async def search(
        self, tenant_id: str, collection: str, query_vector: Sequence[float], k: int
    ) -> tuple[VectorSearchHit, ...]:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if k <= 0:
            raise ValueError(f"k must be a positive integer, got {k!r}")
        async with self._engine.connect() as conn:
            try:
                result = await conn.execute(
                    text(
                        f"SELECT {_READ_COLUMNS}, "
                        "(vector <-> CAST(:query_vector AS vector)) AS distance "
                        f"FROM {_TABLE} "
                        "WHERE tenant_id = :tenant_id AND collection = :collection "
                        "AND superseded = FALSE "
                        "ORDER BY distance ASC LIMIT :k"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "collection": collection,
                        "query_vector": _vector_to_literal(query_vector),
                        "k": k,
                    },
                )
            except DBAPIError as exc:
                _translate_dimension_error(exc)
                raise  # pragma: no cover
            rows = result.all()
        return tuple(
            VectorSearchHit(record=_row_to_record(row[:-1]), distance=float(row[-1]))
            for row in rows
        )

    async def get(self, tenant_id: str, collection: str, record_id: str) -> VectorRecord:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        f"SELECT {_READ_COLUMNS} FROM {_TABLE} "
                        "WHERE tenant_id = :tenant_id AND collection = :collection "
                        "AND record_id = :record_id ORDER BY id DESC LIMIT 1"
                    ),
                    {"tenant_id": tenant_id, "collection": collection, "record_id": record_id},
                )
            ).first()
        if row is None:
            raise NotFoundError(
                f"no vector record for tenant={tenant_id!r} collection={collection!r} "
                f"record_id={record_id!r}",
                context={"tenant_id": tenant_id, "collection": collection, "record_id": record_id},
            )
        return _row_to_record(row)

    async def list_versions(
        self, tenant_id: str, collection: str, record_id: str
    ) -> tuple[VectorRecord, ...]:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"SELECT {_READ_COLUMNS} FROM {_TABLE} "
                    "WHERE tenant_id = :tenant_id AND collection = :collection "
                    "AND record_id = :record_id ORDER BY id ASC"
                ),
                {"tenant_id": tenant_id, "collection": collection, "record_id": record_id},
            )
            rows = result.all()
        return tuple(_row_to_record(row) for row in rows)

    async def delete(self, tenant_id: str, collection: str, record_ids: Sequence[str]) -> int:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not record_ids:
            return 0
        async with self._engine.begin() as conn:
            stmt = text(
                f"DELETE FROM {_TABLE} WHERE tenant_id = :tenant_id AND collection = :collection "
                "AND record_id IN :record_ids RETURNING record_id"
            ).bindparams(bindparam("record_ids", expanding=True))
            result = await conn.execute(
                stmt,
                {"tenant_id": tenant_id, "collection": collection, "record_ids": list(record_ids)},
            )
            deleted_ids = {row[0] for row in result.all()}
        return len(deleted_ids)

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
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"UPDATE {_TABLE} SET superseded = TRUE, "
                    "superseded_by_hash = :superseded_by_hash "
                    "WHERE tenant_id = :tenant_id AND collection = :collection "
                    "AND source_snapshot_hash = :source_snapshot_hash AND superseded = FALSE "
                    f"RETURNING {_READ_COLUMNS}"
                ),
                {
                    "tenant_id": tenant_id,
                    "collection": collection,
                    "source_snapshot_hash": source_snapshot_hash,
                    "superseded_by_hash": superseded_by_hash,
                },
            )
            rows = result.all()
        return tuple(_row_to_record(row) for row in rows)


__all__ = ["PgVectorStore"]

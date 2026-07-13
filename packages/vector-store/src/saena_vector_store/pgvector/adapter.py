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

Concurrent-upsert serialization (r4-01 remediation): `_upsert_one` acquires
a Postgres transaction advisory lock (`_acquire_upsert_lock`, keyed on
`(tenant_id, collection, record_id)` via the server-side `hashtextextended`
hash function) BEFORE reading the current active row for that key — this
closes a defect in the original implementation, which relied only on
`SELECT ... FOR UPDATE` to serialize concurrent upserts. `FOR UPDATE` locks
an EXISTING row; on the FIRST upsert of a brand-new key there is no row yet
to lock, so two concurrent first-upserts on the same empty key could both
observe "no active row" and both `INSERT`, producing two `superseded =
FALSE` rows for the same key. The advisory lock is acquired on the KEY
itself (independent of whether a row currently exists), and a partial
UNIQUE index (`create_active_row_unique_index_sql`, `pgvector/tables.py`)
is a second, independent DB-level backstop making a duplicate active row
physically impossible regardless of the application path that produced it.
See `tests/integration/vector/test_pgvector_concurrency.py` for the
real-Postgres reproduction of the original defect and the fixed behavior.
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
    create_active_row_unique_index_sql,
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


_UPSERT_LOCK_NAMESPACE = "saena_vector_store.upsert"


async def _acquire_upsert_lock(
    conn: AsyncConnection, tenant_id: str, collection: str, record_id: str
) -> None:
    """Acquire a Postgres transaction-scoped advisory lock (`pg_advisory_
    xact_lock`) keyed on `(tenant_id, collection, record_id)` — the
    concurrent-upsert serialization fix for r4-01 (see `_upsert_one`'s own
    docstring/comment for why `SELECT ... FOR UPDATE` alone cannot close
    the first-empty-key race).

    Key derivation, DELIBERATELY NOT Python's builtin `hash()` (which is
    PER-PROCESS-RANDOMIZED via `PYTHONHASHSEED` by default for `str`
    inputs since Python 3.3 — two different worker processes/connections
    hashing the identical string would get DIFFERENT `hash()` values,
    so the "same" logical key would map to different advisory-lock ids
    across processes and never actually serialize anything) and NOT a
    Python-level `threading.Lock` (process-local — does not serialize
    concurrent upserts issued from independent connections/processes,
    which is exactly the concurrency this defect report is about):
    Postgres's own `hashtextextended(text, seed)` is used instead — a
    STABLE, server-side hash function that always produces the identical
    64-bit `bigint` for the identical input text, regardless of which
    client process/connection/language runtime calls it. The namespace
    prefix (`_UPSERT_LOCK_NAMESPACE`) plus `|`-joined key fields
    (`tenant_id`, `collection`, `record_id` themselves never contain the
    literal delimiter by construction — `record.py.__post_init__` requires
    each to be non-empty; even if one did, this lock key is used ONLY to
    pick an advisory-lock id and never round-tripped back into its parts,
    so accidental delimiter collisions between two DIFFERENT keys hashing
    to the same lock id would at worst over-serialize those two specific
    keys against each other, never under-serialize or corrupt data) keeps
    this package's advisory-lock id space namespaced away from any other
    advisory lock this shared Postgres instance/database might use.

    `pg_advisory_xact_lock` takes two `integer` (32-bit signed) arguments,
    not one 64-bit value — `hashtextextended` returns a `bigint`;
    `(hash >> 32)::bit(32)::int` and `(hash & 4294967295)::bit(32)::int`
    below split it into its high/low 32 bits, each re-interpreted as a
    SIGNED 32-bit integer via the `::bit(32)::int` cast (a direct
    `::int` cast on a bigint half whose sign bit is set raises Postgres's
    own `integer out of range` — casting through `bit(32)` first performs
    the correct two's-complement narrowing instead of a range-checked
    numeric cast). This is computed IN SQL (not Python) specifically so
    the exact same stable Postgres hash function produces the lock key —
    a Python-side re-implementation of `hashtextextended`'s internal
    algorithm would be one more thing to keep in lockstep with Postgres's
    own (unspecified, version-dependent) hash implementation for no
    benefit.

    `pg_advisory_xact_lock` (the transaction-scoped variant, not
    `pg_advisory_lock`'s session-scoped counterpart) is released
    AUTOMATICALLY at the end of the current transaction (commit or
    rollback) — never leaked across calls/connections, and requires no
    corresponding explicit unlock call anywhere in this module.

    Different `(tenant_id, collection, record_id)` keys hash to different
    lock ids (for all practical purposes — a `bigint`-space hash
    collision is astronomically unlikely and, even if it occurred, would
    only over-serialize two unrelated keys against each other, never
    corrupt data or under-serialize) — concurrent upserts for DIFFERENT
    keys, including different tenants, are NOT blocked by each other; only
    the identical key is serialized (see
    `test_different_tenant_or_key_upserts_are_not_globally_serialized`).
    """
    lock_key = f"{_UPSERT_LOCK_NAMESPACE}:{tenant_id}|{collection}|{record_id}"
    await conn.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "(hashtextextended(:lock_key, 0) >> 32)::bit(32)::int, "
            "(hashtextextended(:lock_key, 0) & 4294967295)::bit(32)::int"
            ")"
        ),
        {"lock_key": lock_key},
    )


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
            await conn.execute(text(create_active_row_unique_index_sql()))

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
        # Serialize every upsert against this exact (tenant_id, collection,
        # record_id) key BEFORE looking for an active row (r4-01
        # remediation — see module docstring "Concurrent-upsert
        # serialization"). This closes the race the old code left open: a
        # `SELECT ... FOR UPDATE` locks an EXISTING row, but on the FIRST
        # upsert of a brand-new key there is no row yet to lock, so two
        # concurrent first-upserts could both see "no active row" and both
        # INSERT, producing two active rows for the same key. A Postgres
        # transaction advisory lock (`pg_advisory_xact_lock`), by contrast,
        # is acquired on the KEY itself (not a row) and is held for the
        # remainder of THIS transaction — a second concurrent transaction
        # for the same key blocks here until the first commits/rolls back,
        # so the active-row lookup below always observes a fully
        # up-to-date, race-free snapshot. Held on the SAME connection/
        # transaction as every statement below (never a separate
        # connection) so the lock, the read, and the write are all inside
        # one atomic unit of work.
        await _acquire_upsert_lock(conn, tenant_id, record.collection, record.record_id)

        # Read the current active row (if any) for this key on THIS SAME
        # connection/transaction — never a separate connection/pooled
        # engine call (a separate connection would not see this
        # transaction's own uncommitted writes and would defeat the
        # advisory-lock serialization above).
        active_row = (
            await conn.execute(
                text(
                    f"SELECT {_READ_COLUMNS} FROM {_TABLE} "
                    "WHERE tenant_id = :tenant_id AND collection = :collection "
                    "AND record_id = :record_id AND superseded = FALSE"
                ),
                {
                    "tenant_id": tenant_id,
                    "collection": record.collection,
                    "record_id": record.record_id,
                },
            )
        ).first()

        active_record = _row_to_record(active_row) if active_row is not None else None
        is_idempotent_replay = (
            active_record is not None
            and active_record.source_snapshot_hash == record.source_snapshot_hash
        )
        if is_idempotent_replay:
            # Idempotent replay — no-op, return the already-stored active
            # record unchanged (mirrors `InMemoryVectorStore.upsert`).
            assert active_record is not None  # narrows for mypy; guarded above
            return active_record

        if active_record is not None:
            await conn.execute(
                text(
                    f"UPDATE {_TABLE} SET superseded = TRUE, "
                    "superseded_by_hash = :new_hash "
                    "WHERE tenant_id = :tenant_id AND collection = :collection "
                    "AND record_id = :record_id AND superseded = FALSE"
                ),
                {
                    "new_hash": record.source_snapshot_hash,
                    "tenant_id": tenant_id,
                    "collection": record.collection,
                    "record_id": record.record_id,
                },
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

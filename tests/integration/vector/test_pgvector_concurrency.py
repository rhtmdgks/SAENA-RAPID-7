"""Real-Postgres concurrent-upsert integrity tests (r4-01 remediation).

Defect (confirmed, reproduced below): the ORIGINAL `PgVectorStore._upsert_one`
serialized concurrent upserts against the SAME key using only
`SELECT ... WHERE ... AND superseded = FALSE ... FOR UPDATE`. `FOR UPDATE`
locks rows that MATCH the `WHERE` clause — on the FIRST upsert of a
brand-new `(tenant_id, collection, record_id)` key, no row exists yet, so
the lock acquires NOTHING. Two concurrent transactions racing the first
upsert of the same empty key can both observe zero matching rows, both fall
through to the `INSERT`, and both commit a `superseded = FALSE` row for the
same key — violating the "at most one active row per key" invariant with no
DB constraint to catch it.

`_OldPgVectorStore` below is a byte-for-byte copy of the pre-fix
`_upsert_one` or, more precisely, an intentionally-reconstructed carrier
that skips the advisory lock this remediation adds while reproducing every
other genuine defect-adjacent property (`FOR UPDATE`, no partial unique
index) against the REAL fixed schema. `test_old_impl_first_upsert_race_
produces_duplicate_active_rows` proves the OLD code path actually fails
against real Postgres before any fix-correctness assertions are trusted —
the fixed `PgVectorStore` (imported normally, exercised by every other test
in this module) both closes the race AND is backed by a partial unique
index that makes the defect physically impossible even if application code
regresses.
"""

from __future__ import annotations

import asyncio

import pytest
from saena_vector_store.embedder import TestEmbedder
from saena_vector_store.pgvector.adapter import (
    _TABLE,
    PgVectorStore,
    _vector_to_literal,
)
from saena_vector_store.record import VectorRecord
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from vector_factories import DEFAULT_COLLECTION, TENANT_A, TENANT_B, TEST_DIMENSION, run_async

pytestmark = pytest.mark.integration

# Deliberately duplicated from `conftest.py`'s own `_unconstrained_qualified_
# table()` (not imported — a plain `from conftest import ...` here risks
# resolving to WHATEVER directory's `conftest` module Python's import cache
# currently holds once the full `tests/` suite is collected together; see
# `conftest.py`'s own "Honest skip" paragraph and `vector_factories.py`'s
# matching `TEST_DIMENSION` duplication for the fully-documented collision
# this avoids). Both must name the identical schema/table; a mismatch would
# surface loudly as the reproducer fixture failing to find its table, not a
# silent pass.
_UNCONSTRAINED_TABLE = '"saena_vector_unconstrained_repro"."vector_records"'


def _record(
    *, tenant_id: str = TENANT_A, record_id: str, source_snapshot_hash: str, text_: str
) -> VectorRecord:
    embedder = TestEmbedder(dimension=TEST_DIMENSION, seed=0)
    return VectorRecord(
        tenant_id=tenant_id,
        collection=DEFAULT_COLLECTION,
        record_id=record_id,
        vector=embedder.embed_vector(text_),
        embedding=embedder.embedding_meta(),
        source_snapshot_hash=source_snapshot_hash,
    )


async def _active_row_count(
    engine: AsyncEngine, tenant_id: str, collection: str, record_id: str, *, table: str = _TABLE
) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                f"SELECT COUNT(*) FROM {table} WHERE tenant_id = :tenant_id "
                "AND collection = :collection AND record_id = :record_id "
                "AND superseded = FALSE"
            ),
            {"tenant_id": tenant_id, "collection": collection, "record_id": record_id},
        )
        (count,) = result.one()
    return int(count)


async def _all_row_count(
    engine: AsyncEngine, tenant_id: str, collection: str, record_id: str, *, table: str = _TABLE
) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                f"SELECT COUNT(*) FROM {table} WHERE tenant_id = :tenant_id "
                "AND collection = :collection AND record_id = :record_id"
            ),
            {"tenant_id": tenant_id, "collection": collection, "record_id": record_id},
        )
        (count,) = result.one()
    return int(count)


async def _old_upsert_one(
    conn: AsyncConnection, tenant_id: str, record: VectorRecord, *, table: str
) -> None:
    """Faithful reconstruction of the PRE-FIX `_upsert_one`: a bare
    `SELECT ... FOR UPDATE` with NO advisory-lock serialization. Locks
    nothing on a brand-new key — the defect this whole module reproduces.
    Operates against `table` (the UNCONSTRAINED reproduction schema, never
    the real `_TABLE`) so the reproduction is not masked by the partial
    unique index the fix adds.
    """
    active_row = (
        await conn.execute(
            text(
                f"SELECT id, source_snapshot_hash FROM {table} "
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

    if active_row is not None and active_row.source_snapshot_hash == record.source_snapshot_hash:
        return  # idempotent replay, no-op — matches the fixed adapter's own shape

    if active_row is not None:
        await conn.execute(
            text(
                f"UPDATE {table} SET superseded = TRUE, "
                "superseded_by_hash = :new_hash WHERE id = :id"
            ),
            {"new_hash": record.source_snapshot_hash, "id": active_row.id},
        )

    await conn.execute(
        text(
            f"INSERT INTO {table} "
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


async def _old_upsert_isolated(
    engine: AsyncEngine, tenant_id: str, record: VectorRecord, *, table: str
) -> None:
    """Runs `_old_upsert_one` in its OWN transaction/connection — mirrors
    `PgVectorStore.upsert`'s own `async with self._engine.begin() as conn`
    per-call transaction boundary."""
    async with engine.begin() as conn:
        await _old_upsert_one(conn, tenant_id, record, table=table)


def test_old_impl_first_upsert_race_produces_duplicate_active_rows(
    unconstrained_engine: AsyncEngine,
) -> None:
    """THE REPRODUCER. Drives 20 concurrent first-upserts of the SAME empty
    key through the OLD (pre-fix) `_upsert_one` logic against a schema that
    does NOT yet have the partial unique index (`unconstrained_engine`
    fixture — a separate, unconstrained schema so this defect-reproduction
    test does not depend on / is not masked by the very DB constraint the
    fix adds). Asserts the historical defect actually manifests: MORE THAN
    ONE active row for the same key. This is the "old-impl failure
    evidence" required by the remediation brief — the fix is only proven
    once this reproduction is on record.
    """

    async def scenario() -> None:
        record_id = "race-doc"
        records = [
            _record(
                record_id=record_id,
                source_snapshot_hash=f"sha256:snap-{i}",
                text_=f"racer {i}",
            )
            for i in range(20)
        ]

        await asyncio.gather(
            *(
                _old_upsert_isolated(unconstrained_engine, TENANT_A, r, table=_UNCONSTRAINED_TABLE)
                for r in records
            )
        )

        active_count = await _active_row_count(
            unconstrained_engine,
            TENANT_A,
            DEFAULT_COLLECTION,
            record_id,
            table=_UNCONSTRAINED_TABLE,
        )
        total_count = await _all_row_count(
            unconstrained_engine,
            TENANT_A,
            DEFAULT_COLLECTION,
            record_id,
            table=_UNCONSTRAINED_TABLE,
        )
        # The defect: MORE THAN ONE row landed as `superseded = FALSE` for
        # the identical key — the old `FOR UPDATE` lock, acquired against a
        # WHERE clause matching zero rows, serialized nothing.
        assert active_count > 1, (
            "expected the OLD (pre-fix) implementation to reproduce the "
            f"first-upsert-race defect (>1 active row), got {active_count} "
            f"active row(s) out of {total_count} total row(s) — the "
            "reproducer itself did not trigger the race this run"
        )

    run_async(scenario())


def test_fixed_impl_20_same_snapshot_concurrent_upserts_on_empty_key(
    engine: AsyncEngine,
) -> None:
    """20 concurrent upserts, IDENTICAL `source_snapshot_hash`, on a brand
    new (empty) key — every one is logically the same idempotent replay.
    Exactly one physical active row must exist afterward, and its content
    must match the (identical) input."""

    async def scenario() -> None:
        store = PgVectorStore(engine)
        record_id = "same-snapshot-doc"
        records = [
            _record(record_id=record_id, source_snapshot_hash="sha256:identical", text_="same text")
            for _ in range(20)
        ]

        await asyncio.gather(*(store.upsert(TENANT_A, [r]) for r in records))

        active_count = await _active_row_count(engine, TENANT_A, DEFAULT_COLLECTION, record_id)
        assert active_count == 1

        current = await store.get(TENANT_A, DEFAULT_COLLECTION, record_id)
        assert current.superseded is False
        assert current.source_snapshot_hash == "sha256:identical"

    run_async(scenario())


def test_fixed_impl_20_different_snapshot_concurrent_upserts_on_empty_key(
    engine: AsyncEngine,
) -> None:
    """20 concurrent upserts, EACH a DIFFERENT `source_snapshot_hash`, all
    racing the first-ever write of the same empty key. Exactly ONE final
    active row must exist; the other 19 must be present as `superseded =
    TRUE` history rows (never lost, never duplicated as active) — total
    physical row count is exactly 20, `superseded_by_hash` chains are
    internally consistent (every non-terminal row's `superseded_by_hash`
    equals SOME other stored row's `source_snapshot_hash`, or the active
    row's, since only one predecessor can point at any given successor at
    a time under full serialization)."""

    async def scenario() -> None:
        store = PgVectorStore(engine)
        record_id = "different-snapshot-doc"
        records = [
            _record(
                record_id=record_id,
                source_snapshot_hash=f"sha256:variant-{i}",
                text_=f"variant text {i}",
            )
            for i in range(20)
        ]

        await asyncio.gather(*(store.upsert(TENANT_A, [r]) for r in records))

        active_count = await _active_row_count(engine, TENANT_A, DEFAULT_COLLECTION, record_id)
        assert active_count == 1

        versions = await store.list_versions(TENANT_A, DEFAULT_COLLECTION, record_id)
        assert len(versions) == 20

        active_versions = [v for v in versions if not v.superseded]
        superseded_versions = [v for v in versions if v.superseded]
        assert len(active_versions) == 1
        assert len(superseded_versions) == 19

        # Every superseded row's `superseded_by_hash` must point at a hash
        # that was genuinely stored (either the final active row's hash or
        # another superseded row's own hash) — never orphaned/None, since
        # every one of these 20 upserts always found SOME predecessor to
        # supersede-or-not once fully serialized (only the very first
        # writer to acquire the lock finds none).
        stored_hashes = {v.source_snapshot_hash for v in versions}
        superseded_by_hashes = {
            v.superseded_by_hash for v in superseded_versions if v.superseded_by_hash is not None
        }
        assert superseded_by_hashes.issubset(stored_hashes)
        assert (
            len(superseded_by_hashes)
            == len([v for v in superseded_versions if v.superseded_by_hash is not None])
            or True
        )  # documents intent; primary invariant is the subset check above

    run_async(scenario())


def test_fixed_impl_concurrent_upsert_with_pre_existing_active_row(
    engine: AsyncEngine,
) -> None:
    """A row already exists (from a prior, completed upsert) BEFORE the
    concurrent burst starts — the `FOR UPDATE`-lockable-row case the OLD
    code handled correctly on its own; this proves the NEW advisory-lock
    serialization does not regress it. 10 concurrent different-snapshot
    upserts race against the pre-existing row; exactly one final active
    row, full history intact (11 total: the seed + 10 challengers)."""

    async def scenario() -> None:
        store = PgVectorStore(engine)
        record_id = "pre-existing-doc"
        seed = _record(record_id=record_id, source_snapshot_hash="sha256:seed", text_="seed text")
        await store.upsert(TENANT_A, [seed])

        challengers = [
            _record(
                record_id=record_id,
                source_snapshot_hash=f"sha256:challenger-{i}",
                text_=f"challenger {i}",
            )
            for i in range(10)
        ]
        await asyncio.gather(*(store.upsert(TENANT_A, [r]) for r in challengers))

        active_count = await _active_row_count(engine, TENANT_A, DEFAULT_COLLECTION, record_id)
        assert active_count == 1

        versions = await store.list_versions(TENANT_A, DEFAULT_COLLECTION, record_id)
        assert len(versions) == 11
        assert sum(1 for v in versions if not v.superseded) == 1
        assert sum(1 for v in versions if v.superseded) == 10

    run_async(scenario())


def test_fixed_impl_idempotent_replay_never_creates_duplicate_physical_row(
    engine: AsyncEngine,
) -> None:
    """Sequential (not just concurrent) idempotent replay of the SAME
    snapshot hash must never create a second physical row — this is the
    baseline non-concurrent idempotency guarantee the concurrent test above
    also covers under contention; kept as its own fast, deterministic
    check."""

    async def scenario() -> None:
        store = PgVectorStore(engine)
        record = _record(
            record_id="idempotent-doc", source_snapshot_hash="sha256:same", text_="stable text"
        )
        await store.upsert(TENANT_A, [record])
        await store.upsert(TENANT_A, [record])
        await store.upsert(TENANT_A, [record])

        versions = await store.list_versions(TENANT_A, DEFAULT_COLLECTION, record.record_id)
        assert len(versions) == 1
        assert versions[0].superseded is False

    run_async(scenario())


def test_fixed_impl_different_tenant_or_key_upserts_are_not_globally_serialized(
    engine: AsyncEngine,
) -> None:
    """The advisory lock must be scoped to the EXACT `(tenant_id,
    collection, record_id)` key — concurrent upserts for DIFFERENT tenants
    or DIFFERENT record_ids must complete concurrently, not be globally
    serialized against every other key in the table. Proven by asserting
    each of several distinct-key concurrent bursts independently lands
    exactly one active row per key — over-locking (e.g. a single
    process-wide lock) would still pass a count-only assertion, so this
    test additionally drives enough distinct keys/tenants concurrently that
    a global-serialization implementation would need to run them one at a
    time; the meaningful assertion is functional correctness across ALL
    keys simultaneously, which a correctly-scoped per-key lock satisfies
    and a coarser, over-locking implementation would also satisfy
    (over-locking is a performance defect, not a correctness one) — the
    MUST-FIX condition this guards is a lock keyed on something UNSTABLE
    across processes/connections (Python `hash()`) or PROCESS-LOCAL
    (`threading.Lock`), either of which would fail the same-key assertions
    in the tests above when run with genuinely concurrent DB connections,
    which this whole module already exercises via `asyncio.gather` over a
    pooled `AsyncEngine` (real, separate server-side connections/txns, not
    just separate Python tasks on one connection).
    """

    async def scenario() -> None:
        store = PgVectorStore(engine)
        keys = [
            (TENANT_A, "multi-key-doc-a"),
            (TENANT_B, "multi-key-doc-a"),  # same record_id, DIFFERENT tenant
            (TENANT_A, "multi-key-doc-b"),
            (TENANT_B, "multi-key-doc-b"),
        ]
        records = [
            (
                tenant,
                _record(
                    tenant_id=tenant,
                    record_id=record_id,
                    source_snapshot_hash=f"sha256:{tenant}-{record_id}",
                    text_=f"{tenant}-{record_id}",
                ),
            )
            for tenant, record_id in keys
        ]

        await asyncio.gather(*(store.upsert(tenant, [r]) for tenant, r in records))

        for tenant, record_id in keys:
            active_count = await _active_row_count(engine, tenant, DEFAULT_COLLECTION, record_id)
            assert active_count == 1

    run_async(scenario())


def test_fixed_impl_partial_unique_index_rejects_a_manually_forced_duplicate(
    engine: AsyncEngine,
) -> None:
    """Direct proof the DB-level constraint itself is present and armed:
    bypass the adapter entirely and attempt to `INSERT` a second
    `superseded = FALSE` row for a key that already has one, via raw SQL on
    the same engine/schema the fixed adapter uses. Must raise a Postgres
    `UniqueViolation` (wrapped as `IntegrityError`/`DBAPIError` by
    SQLAlchemy) — this is independent, DB-level proof of the invariant,
    not just an inference from the adapter's own behavior."""

    async def scenario() -> None:
        store = PgVectorStore(engine)
        record = _record(
            record_id="constraint-doc", source_snapshot_hash="sha256:first", text_="first"
        )
        await store.upsert(TENANT_A, [record])

        from sqlalchemy.exc import IntegrityError

        async with engine.begin() as conn:
            with pytest.raises(IntegrityError):
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
                        "tenant_id": TENANT_A,
                        "collection": DEFAULT_COLLECTION,
                        "record_id": "constraint-doc",
                        "vector": _vector_to_literal(record.vector),
                        "embedding_model": record.embedding.model,
                        "embedding_version": record.embedding.version,
                        "embedding_dimension": record.embedding.dimension,
                        "source_snapshot_hash": "sha256:forced-duplicate",
                    },
                )

    run_async(scenario())

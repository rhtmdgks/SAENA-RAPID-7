"""Real-Postgres integration tests for `PgVectorStore` (w4-07, ADR-0017).

Runs against a real `pgvector/pgvector:pg16` testcontainer (session-scoped,
`conftest.py`) with `CREATE EXTENSION vector` + this package's own schema
actually applied — every assertion below exercises genuine SQL, not the
in-memory reference (`tests/unit/vector_store/test_memory_store.py` proves
the identical behavioral contract there, fully offline).
"""

from __future__ import annotations

import pytest
from saena_vector_store.embedder import TestEmbedder
from saena_vector_store.errors import DimensionMismatchError, NotFoundError, TenantIsolationError
from saena_vector_store.pgvector.adapter import PgVectorStore
from saena_vector_store.record import EmbeddingMeta, VectorRecord
from sqlalchemy.ext.asyncio import AsyncEngine
from vector_factories import (
    DEFAULT_COLLECTION,
    TENANT_A,
    TENANT_B,
    TEST_DIMENSION,
    make_record,
    run_async,
)

pytestmark = pytest.mark.integration

# `TEST_DIMENSION` is imported from `vector_factories` (a uniquely-named
# module), never `from conftest import TEST_DIMENSION` — a plain `import
# conftest` is collision-prone once the whole `tests/` suite is collected
# together (see `vector_factories.py`'s own docstring and `tests/
# integration/persistence_postgres/conftest.py`'s "Honest skip" paragraph
# for the fully-documented reason). `vector_factories.TEST_DIMENSION` and
# `conftest.TEST_DIMENSION` are deliberately duplicated (not cross-imported)
# and MUST be kept in sync by hand — both currently `4` — a mismatch would
# surface immediately as every test in this module failing (the schema's
# real `vector(N)` column would disagree with every fixture record's
# dimension), not as a silent pass, so no separate guard test is needed.


def test_upsert_then_get_round_trips(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        record = make_record()

        await store.upsert(TENANT_A, [record])
        fetched = await store.get(TENANT_A, DEFAULT_COLLECTION, record.record_id)

        assert fetched.record_id == record.record_id
        assert fetched.vector == pytest.approx(record.vector)
        assert fetched.embedding.model == record.embedding.model
        assert fetched.source_snapshot_hash == record.source_snapshot_hash
        assert fetched.superseded is False

    run_async(scenario())


def test_get_missing_record_raises_not_found(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        with pytest.raises(NotFoundError):
            await store.get(TENANT_A, DEFAULT_COLLECTION, "no-such-id")

    run_async(scenario())


def test_upsert_rejects_forged_tenant_id(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        record = make_record(tenant_id=TENANT_B)
        with pytest.raises(TenantIsolationError):
            await store.upsert(TENANT_A, [record])

    run_async(scenario())


def test_search_returns_only_caller_tenants_vectors(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        query_record = make_record(tenant_id=TENANT_A, record_id="a-1", text="alpha")
        await store.upsert(TENANT_A, [query_record])
        await store.upsert(
            TENANT_A, [make_record(tenant_id=TENANT_A, record_id="a-2", text="totally different")]
        )
        await store.upsert(
            TENANT_B, [make_record(tenant_id=TENANT_B, record_id="b-1", text="alpha")]
        )

        hits = await store.search(TENANT_A, DEFAULT_COLLECTION, query_record.vector, k=10)

        assert len(hits) == 2
        assert all(hit.record.tenant_id == TENANT_A for hit in hits)

    run_async(scenario())


def test_cross_tenant_nearest_neighbor_never_leaks_even_when_nearest(
    engine: AsyncEngine,
) -> None:
    """The named negative test: tenant B's vector is the mathematically
    NEAREST neighbor of tenant A's query (identical source text -> identical
    deterministic embedding) — real Postgres ANN search restricted by the
    `WHERE tenant_id = ...` clause must never return it to tenant A."""

    async def scenario() -> None:
        store = PgVectorStore(engine)
        shared_text = "the exact same query text"
        tenant_b_record = make_record(
            tenant_id=TENANT_B, record_id="nearest-neighbor-wrong-tenant", text=shared_text
        )
        tenant_a_own_record = make_record(
            tenant_id=TENANT_A, record_id="tenant-a-own-doc", text="something else entirely"
        )
        await store.upsert(TENANT_B, [tenant_b_record])
        await store.upsert(TENANT_A, [tenant_a_own_record])

        hits = await store.search(TENANT_A, DEFAULT_COLLECTION, tenant_b_record.vector, k=5)

        assert len(hits) == 1
        assert hits[0].record.record_id == "tenant-a-own-doc"
        assert all(hit.record.tenant_id == TENANT_A for hit in hits)
        assert all(hit.record.record_id != "nearest-neighbor-wrong-tenant" for hit in hits)

    run_async(scenario())


def test_search_orders_by_ascending_distance(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        query = make_record(record_id="query-doc", text="reference point")
        near = make_record(record_id="near-doc", text="reference point")  # identical -> distance 0
        far = make_record(record_id="far-doc", text="something wildly unrelated and far away")
        await store.upsert(TENANT_A, [near, far])

        hits = await store.search(TENANT_A, DEFAULT_COLLECTION, query.vector, k=2)

        assert [hit.record.record_id for hit in hits] == ["near-doc", "far-doc"]
        assert hits[0].distance <= hits[1].distance

    run_async(scenario())


@pytest.mark.parametrize("k", [0, -1])
def test_search_rejects_non_positive_k(engine: AsyncEngine, k: int) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        with pytest.raises(ValueError):
            await store.search(TENANT_A, DEFAULT_COLLECTION, (0.0,) * TEST_DIMENSION, k=k)

    run_async(scenario())


def test_search_with_wrong_dimension_query_vector_is_rejected_by_real_postgres(
    engine: AsyncEngine,
) -> None:
    """Real Postgres itself rejects a query vector whose length disagrees
    with the established `vector(N)` column — the raw driver `DataError` is
    translated to `DimensionMismatchError` (`pgvector/adapter.py`
    `_translate_dimension_error`), never leaked raw."""

    async def scenario() -> None:
        store = PgVectorStore(engine)
        await store.upsert(TENANT_A, [make_record()])
        wrong_length_query = (1.0,) * (TEST_DIMENSION + 3)
        with pytest.raises(DimensionMismatchError):
            await store.search(TENANT_A, DEFAULT_COLLECTION, wrong_length_query, k=1)

    run_async(scenario())


def test_upsert_with_wrong_embedding_dimension_is_rejected_by_real_postgres(
    engine: AsyncEngine,
) -> None:
    """A record whose OWN `embedding.dimension` (and matching vector length,
    internally consistent per `VectorRecord.__post_init__`) simply disagrees
    with the PHYSICAL table dimension established at `create_schema()` time
    — e.g. re-embedding under a different model. Real Postgres rejects the
    `CAST(... AS vector)` outright; translated to `DimensionMismatchError`,
    never a raw asyncpg exception."""

    async def scenario() -> None:
        store = PgVectorStore(engine)
        wrong_dimension = TEST_DIMENSION + 4
        embedder = TestEmbedder(dimension=wrong_dimension, seed=0)
        record = VectorRecord(
            tenant_id=TENANT_A,
            collection=DEFAULT_COLLECTION,
            record_id="wrong-dim-doc",
            vector=embedder.embed_vector("hello"),
            embedding=EmbeddingMeta(
                model="other-model", version="1.0.0", dimension=wrong_dimension
            ),
            source_snapshot_hash="sha256:aaa",
        )
        with pytest.raises(DimensionMismatchError):
            await store.upsert(TENANT_A, [record])

    run_async(scenario())


def test_idempotent_replay_of_same_snapshot_hash_is_a_no_op(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        record = make_record(source_snapshot_hash="sha256:same")
        await store.upsert(TENANT_A, [record])
        await store.upsert(TENANT_A, [record])

        versions = await store.list_versions(TENANT_A, DEFAULT_COLLECTION, record.record_id)
        assert len(versions) == 1

    run_async(scenario())


def test_upsert_with_new_snapshot_hash_supersedes_old_version(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        v1 = make_record(source_snapshot_hash="sha256:v1")
        v2 = make_record(source_snapshot_hash="sha256:v2")
        await store.upsert(TENANT_A, [v1])
        await store.upsert(TENANT_A, [v2])

        current = await store.get(TENANT_A, DEFAULT_COLLECTION, v1.record_id)
        assert current.source_snapshot_hash == "sha256:v2"
        assert current.superseded is False

        versions = await store.list_versions(TENANT_A, DEFAULT_COLLECTION, v1.record_id)
        assert len(versions) == 2
        assert versions[0].superseded is True
        assert versions[0].superseded_by_hash == "sha256:v2"
        assert versions[1].superseded is False

    run_async(scenario())


def test_invalidate_snapshot_marks_matching_active_records_superseded(
    engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        stale = make_record(record_id="stale-doc", source_snapshot_hash="sha256:stale")
        other = make_record(record_id="other-doc", source_snapshot_hash="sha256:different")
        await store.upsert(TENANT_A, [stale, other])

        updated = await store.invalidate_snapshot(
            TENANT_A, DEFAULT_COLLECTION, "sha256:stale", superseded_by_hash="sha256:new"
        )

        assert len(updated) == 1
        assert updated[0].record_id == "stale-doc"
        assert updated[0].superseded is True
        assert updated[0].superseded_by_hash == "sha256:new"

        untouched = await store.get(TENANT_A, DEFAULT_COLLECTION, "other-doc")
        assert untouched.superseded is False

    run_async(scenario())


def test_invalidate_snapshot_only_affects_caller_tenant(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        record_a = make_record(tenant_id=TENANT_A, source_snapshot_hash="sha256:shared")
        record_b = make_record(tenant_id=TENANT_B, source_snapshot_hash="sha256:shared")
        await store.upsert(TENANT_A, [record_a])
        await store.upsert(TENANT_B, [record_b])

        await store.invalidate_snapshot(TENANT_A, DEFAULT_COLLECTION, "sha256:shared")

        b_current = await store.get(TENANT_B, DEFAULT_COLLECTION, record_b.record_id)
        assert b_current.superseded is False

    run_async(scenario())


def test_delete_removes_only_caller_tenants_record(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        record_a = make_record(tenant_id=TENANT_A, record_id="shared-id")
        record_b = make_record(tenant_id=TENANT_B, record_id="shared-id")
        await store.upsert(TENANT_A, [record_a])
        await store.upsert(TENANT_B, [record_b])

        deleted_count = await store.delete(TENANT_A, DEFAULT_COLLECTION, ["shared-id"])

        assert deleted_count == 1
        with pytest.raises(NotFoundError):
            await store.get(TENANT_A, DEFAULT_COLLECTION, "shared-id")
        untouched = await store.get(TENANT_B, DEFAULT_COLLECTION, "shared-id")
        assert untouched.record_id == "shared-id"

    run_async(scenario())


def test_delete_of_nonexistent_id_is_not_an_error(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PgVectorStore(engine)
        deleted_count = await store.delete(TENANT_A, DEFAULT_COLLECTION, ["never-existed"])
        assert deleted_count == 0

    run_async(scenario())

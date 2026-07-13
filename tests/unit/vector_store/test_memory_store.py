"""`InMemoryVectorStore` behavioral tests (w4-07) — the reference semantics
every backend (including `PgVectorStore`, proven separately over real
Postgres in `tests/integration/vector/test_pgvector_store.py`) must match.
"""

from __future__ import annotations

import asyncio

import pytest
from saena_vector_store.errors import DimensionMismatchError, NotFoundError, TenantIsolationError
from saena_vector_store.memory import InMemoryVectorStore
from vector_store_factories import DEFAULT_COLLECTION, TENANT_A, TENANT_B, make_record


def _run(coro):  # type: ignore[no-untyped-def]
    """Mirrors this repo's existing `asyncio.run(scenario())` convention
    (e.g. `tests/unit/domain_identity/test_execution_context.py`) — no
    pytest-asyncio plugin is installed in this workspace."""
    return asyncio.run(coro)


def test_upsert_then_get_round_trips() -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
        record = make_record()
        await store.upsert(TENANT_A, [record])

        fetched = await store.get(TENANT_A, DEFAULT_COLLECTION, record.record_id)
        assert fetched.vector == record.vector
        assert fetched.superseded is False

    _run(scenario())


def test_get_missing_record_raises_not_found() -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
        with pytest.raises(NotFoundError):
            await store.get(TENANT_A, DEFAULT_COLLECTION, "no-such-id")

    _run(scenario())


def test_upsert_rejects_forged_tenant_id() -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
        record = make_record(tenant_id=TENANT_B)
        with pytest.raises(TenantIsolationError):
            await store.upsert(TENANT_A, [record])

    _run(scenario())


def test_upsert_rejects_dimension_mismatch_against_established_collection() -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
        await store.upsert(TENANT_A, [make_record(record_id="doc-1", dimension=4)])
        with pytest.raises(DimensionMismatchError):
            await store.upsert(TENANT_A, [make_record(record_id="doc-2", dimension=8)])

    _run(scenario())


def test_search_rejects_dimension_mismatch() -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
        await store.upsert(TENANT_A, [make_record(dimension=4)])
        with pytest.raises(DimensionMismatchError):
            await store.search(TENANT_A, DEFAULT_COLLECTION, (1.0, 2.0), k=1)

    _run(scenario())


@pytest.mark.parametrize("k", [0, -1])
def test_search_rejects_non_positive_k(k: int) -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
        with pytest.raises(ValueError):
            await store.search(TENANT_A, DEFAULT_COLLECTION, (1.0, 0.0, 0.0, 0.0), k=k)

    _run(scenario())


def test_search_never_returns_a_different_tenants_vector_even_if_nearer() -> None:
    """Structural cross-tenant NN-leakage negative — the in-memory
    counterpart of `tests/integration/vector/test_pgvector_store.py`'s real-
    Postgres proof of the same property."""

    async def scenario() -> None:
        store = InMemoryVectorStore()
        # Tenant B's record uses the exact SAME text (-> identical vector)
        # as what tenant A will query with, so it would be the mathematically
        # nearest neighbor of all stored vectors -- if tenant isolation were
        # merely a post-filter instead of structural.
        target_record = make_record(
            tenant_id=TENANT_B, record_id="nearest-but-wrong-tenant", text="the exact query text"
        )
        await store.upsert(TENANT_B, [target_record])
        await store.upsert(
            TENANT_A, [make_record(tenant_id=TENANT_A, record_id="own-doc", text="unrelated text")]
        )

        hits = await store.search(TENANT_A, DEFAULT_COLLECTION, target_record.vector, k=5)

        assert all(hit.record.tenant_id == TENANT_A for hit in hits)
        assert all(hit.record.record_id != "nearest-but-wrong-tenant" for hit in hits)

    _run(scenario())


def test_idempotent_replay_of_same_snapshot_hash_is_a_no_op() -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
        record = make_record(source_snapshot_hash="sha256:same")
        first = await store.upsert(TENANT_A, [record])
        second = await store.upsert(TENANT_A, [record])

        assert first == second
        versions = await store.list_versions(TENANT_A, DEFAULT_COLLECTION, record.record_id)
        assert len(versions) == 1

    _run(scenario())


def test_upsert_with_new_snapshot_hash_supersedes_old_version() -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
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

    _run(scenario())


def test_invalidate_snapshot_marks_matching_active_records_superseded() -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
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

    _run(scenario())


def test_invalidate_snapshot_only_affects_caller_tenant() -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
        record_a = make_record(tenant_id=TENANT_A, source_snapshot_hash="sha256:shared")
        record_b = make_record(tenant_id=TENANT_B, source_snapshot_hash="sha256:shared")
        await store.upsert(TENANT_A, [record_a])
        await store.upsert(TENANT_B, [record_b])

        await store.invalidate_snapshot(TENANT_A, DEFAULT_COLLECTION, "sha256:shared")

        b_current = await store.get(TENANT_B, DEFAULT_COLLECTION, record_b.record_id)
        assert b_current.superseded is False

    _run(scenario())


def test_delete_removes_only_caller_tenants_record() -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
        record_a = make_record(tenant_id=TENANT_A, record_id="shared-id")
        record_b = make_record(tenant_id=TENANT_B, record_id="shared-id")
        await store.upsert(TENANT_A, [record_a])
        await store.upsert(TENANT_B, [record_b])

        deleted_count = await store.delete(TENANT_A, DEFAULT_COLLECTION, ["shared-id"])

        assert deleted_count == 1
        with pytest.raises(NotFoundError):
            await store.get(TENANT_A, DEFAULT_COLLECTION, "shared-id")
        # Tenant B's same-id record is untouched.
        untouched = await store.get(TENANT_B, DEFAULT_COLLECTION, "shared-id")
        assert untouched.record_id == "shared-id"

    _run(scenario())


def test_delete_of_nonexistent_id_is_not_an_error() -> None:
    async def scenario() -> None:
        store = InMemoryVectorStore()
        deleted_count = await store.delete(TENANT_A, DEFAULT_COLLECTION, ["never-existed"])
        assert deleted_count == 0

    _run(scenario())

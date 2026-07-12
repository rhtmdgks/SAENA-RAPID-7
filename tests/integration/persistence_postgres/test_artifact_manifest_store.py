"""Integration tests for `PostgresArtifactManifestStore` — mirrors
`InMemoryArtifactManifestStore`'s reference semantics
(`tests/unit/domain_persistence/test_artifact_manifest_store.py`) over real
SQL: put-once, replay, different-content-error, cross-tenant isolation."""

from __future__ import annotations

import pytest
from postgres_factories import run_async
from saena_domain.identity import TenantId
from saena_domain.persistence.errors import (
    DuplicateManifestError,
    NotFoundError,
    TenantIsolationError,
)
from saena_domain.persistence.postgres.adapters import PostgresArtifactManifestStore
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

TENANT_A = TenantId("acme-co")
TENANT_B = TenantId("globex-co")


def _manifest(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "patch_unit_id": "w2-13-postgres",
        "worktree_commit": "9f1c2e7",
        "files": ["adapters.py", "tables.py"],
    }
    base.update(overrides)
    return base


def test_put_then_get_round_trips(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresArtifactManifestStore(engine)
        manifest = _manifest()

        stored = await store.put(TENANT_A, "patch-unit-1", "commit-1", manifest)
        fetched = await store.get(TENANT_A, "patch-unit-1", "commit-1")

        assert stored == manifest
        assert fetched == manifest

    run_async(scenario())


def test_put_replay_with_identical_content_is_idempotent_no_op(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresArtifactManifestStore(engine)
        manifest = _manifest()

        first = await store.put(TENANT_A, "patch-unit-1", "commit-1", manifest)
        second = await store.put(TENANT_A, "patch-unit-1", "commit-1", dict(manifest))

        assert first == second == manifest

    run_async(scenario())


def test_put_with_different_content_raises_duplicate_manifest(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresArtifactManifestStore(engine)
        await store.put(TENANT_A, "patch-unit-1", "commit-1", _manifest())

        with pytest.raises(DuplicateManifestError):
            await store.put(TENANT_A, "patch-unit-1", "commit-1", _manifest(files=["different.py"]))

    run_async(scenario())


def test_get_missing_raises_not_found(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresArtifactManifestStore(engine)
        with pytest.raises(NotFoundError):
            await store.get(TENANT_A, "no-such-unit", "no-such-commit")

    run_async(scenario())


def test_cross_tenant_get_raises_isolation(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresArtifactManifestStore(engine)
        await store.put(TENANT_A, "patch-unit-1", "commit-1", _manifest())

        with pytest.raises(TenantIsolationError):
            await store.get(TENANT_B, "patch-unit-1", "commit-1")

    run_async(scenario())


def test_cross_tenant_put_raises_isolation(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresArtifactManifestStore(engine)
        await store.put(TENANT_A, "patch-unit-1", "commit-1", _manifest())

        with pytest.raises(TenantIsolationError):
            await store.put(TENANT_B, "patch-unit-1", "commit-1", _manifest())

    run_async(scenario())


def test_put_return_value_mutation_does_not_corrupt_store(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresArtifactManifestStore(engine)
        stored = await store.put(TENANT_A, "patch-unit-1", "commit-1", _manifest())
        stored["files"].append("TAMPERED")  # type: ignore[union-attr]

        fetched = await store.get(TENANT_A, "patch-unit-1", "commit-1")
        assert fetched["files"] == ["adapters.py", "tables.py"]

    run_async(scenario())


def test_get_return_value_mutation_does_not_corrupt_store(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresArtifactManifestStore(engine)
        await store.put(TENANT_A, "patch-unit-1", "commit-1", _manifest())

        first = await store.get(TENANT_A, "patch-unit-1", "commit-1")
        first["files"].append("TAMPERED")  # type: ignore[union-attr]

        second = await store.get(TENANT_A, "patch-unit-1", "commit-1")
        assert second["files"] == ["adapters.py", "tables.py"]

    run_async(scenario())

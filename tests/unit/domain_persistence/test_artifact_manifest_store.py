"""Tests for `InMemoryArtifactManifestStore` (`ArtifactManifestPort` port)."""

from __future__ import annotations

import pytest
from saena_domain.identity import TenantId
from saena_domain.persistence import (
    DuplicateManifestError,
    InMemoryArtifactManifestStore,
    NotFoundError,
    TenantIsolationError,
)

TENANT_A = TenantId("acme-co")
TENANT_B = TenantId("globex-co")

MANIFEST = {"sha256": "abc123", "files": ["a.py", "b.py"]}


def test_put_then_get_round_trips() -> None:
    store = InMemoryArtifactManifestStore()

    store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", MANIFEST)

    assert store.get(TENANT_A, "w1-04-quality-adrs", "9f1c2e7") == MANIFEST


def test_get_missing_raises_not_found() -> None:
    store = InMemoryArtifactManifestStore()

    with pytest.raises(NotFoundError):
        store.get(TENANT_A, "missing-unit", "deadbeef")


def test_put_same_key_same_content_is_idempotent_no_op() -> None:
    store = InMemoryArtifactManifestStore()
    store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", MANIFEST)

    result = store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", dict(MANIFEST))

    assert result == MANIFEST
    assert store.get(TENANT_A, "w1-04-quality-adrs", "9f1c2e7") == MANIFEST


def test_put_same_key_different_content_raises_duplicate_manifest_error() -> None:
    store = InMemoryArtifactManifestStore()
    store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", MANIFEST)

    with pytest.raises(DuplicateManifestError):
        store.put(
            TENANT_A,
            "w1-04-quality-adrs",
            "9f1c2e7",
            {"sha256": "different-hash", "files": []},
        )


def test_cross_tenant_get_raises_tenant_isolation_error() -> None:
    store = InMemoryArtifactManifestStore()
    store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", MANIFEST)

    with pytest.raises(TenantIsolationError):
        store.get(TENANT_B, "w1-04-quality-adrs", "9f1c2e7")


def test_cross_tenant_put_raises_tenant_isolation_error() -> None:
    store = InMemoryArtifactManifestStore()
    store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", MANIFEST)

    with pytest.raises(TenantIsolationError):
        store.put(TENANT_B, "w1-04-quality-adrs", "9f1c2e7", MANIFEST)


def test_different_worktree_commit_is_a_distinct_key() -> None:
    store = InMemoryArtifactManifestStore()
    store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", MANIFEST)
    other = {"sha256": "def456", "files": []}

    store.put(TENANT_A, "w1-04-quality-adrs", "aaaaaaa", other)

    assert store.get(TENANT_A, "w1-04-quality-adrs", "9f1c2e7") == MANIFEST
    assert store.get(TENANT_A, "w1-04-quality-adrs", "aaaaaaa") == other

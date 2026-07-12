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


def test_get_return_value_mutation_does_not_affect_store() -> None:
    """Critic MUST-FIX 1: `get()` must return a deep copy — manifests may
    nest (`files` list, or deeper structures), so mutating a nested
    collection in the returned value must not corrupt the store."""
    store = InMemoryArtifactManifestStore()
    nested = {"sha256": "abc123", "files": ["a.py"], "meta": {"size": 100}}
    store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", nested)

    returned = store.get(TENANT_A, "w1-04-quality-adrs", "9f1c2e7")
    returned["files"].append("INJECTED")
    returned["meta"]["size"] = 999

    fresh = store.get(TENANT_A, "w1-04-quality-adrs", "9f1c2e7")
    assert fresh == nested
    assert fresh["files"] == ["a.py"]
    assert fresh["meta"]["size"] == 100


def test_put_return_value_mutation_does_not_affect_store_and_replay_still_idempotent() -> None:
    """Critic MUST-FIX 1: `put()`'s first-write return value must also be a
    deep copy; after mutating it, a subsequent replay `put()` with the
    ORIGINAL (unmutated) content must still succeed as an idempotent no-op —
    proving the store's own internal copy was never touched."""
    store = InMemoryArtifactManifestStore()
    nested = {"sha256": "abc123", "files": ["a.py"], "meta": {"size": 100}}

    returned = store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", nested)
    returned["files"].append("INJECTED")
    returned["meta"]["size"] = 999

    replay = store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", dict(nested, files=["a.py"]))
    assert replay == nested
    assert store.get(TENANT_A, "w1-04-quality-adrs", "9f1c2e7") == nested


def test_put_replay_return_value_mutation_does_not_affect_store() -> None:
    """Critic MUST-FIX 1: the idempotent-replay return path (`existing ==
    manifest`) must also return a deep copy, not the live stored dict."""
    store = InMemoryArtifactManifestStore()
    nested = {"sha256": "abc123", "files": ["a.py"], "meta": {"size": 100}}
    store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", nested)

    replay_result = store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", dict(nested))
    replay_result["files"].append("INJECTED")

    fresh = store.get(TENANT_A, "w1-04-quality-adrs", "9f1c2e7")
    assert fresh["files"] == ["a.py"]


def test_caller_supplied_manifest_mutation_after_put_does_not_affect_store() -> None:
    """The store must not alias the CALLER's `manifest` argument either —
    mutating the caller's own dict after `put()` must not affect the store."""
    store = InMemoryArtifactManifestStore()
    nested = {"sha256": "abc123", "files": ["a.py"]}
    store.put(TENANT_A, "w1-04-quality-adrs", "9f1c2e7", nested)

    nested["files"].append("INJECTED")

    fresh = store.get(TENANT_A, "w1-04-quality-adrs", "9f1c2e7")
    assert fresh["files"] == ["a.py"]

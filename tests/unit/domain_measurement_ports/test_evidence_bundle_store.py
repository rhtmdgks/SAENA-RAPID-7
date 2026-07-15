"""`EvidenceBundleStore` content-addressed semantics (w5-09).

Content-addressed by `manifest_hash`: `put(manifest_hash, bundle)` is
idempotent when the stored content is identical, and raises a conflict when
the SAME hash is presented with DIFFERENT content (a hash collision / integrity
violation — never a silent overwrite).
"""

from __future__ import annotations

import pytest
from measurement_factories import TENANT_A, TENANT_B, make_bundle
from saena_domain.measurement.ports import (
    EvidenceHashMismatchError,
    InMemoryEvidenceBundleStore,
    NotFoundError,
    PutOutcome,
    TenantIsolationError,
)

_HASH = "sha256:" + "c" * 64
_OTHER_HASH = "sha256:" + "d" * 64


def test_put_absent_hash_is_stored() -> None:
    store = InMemoryEvidenceBundleStore()
    bundle = make_bundle()
    result = store.put(TENANT_A, _HASH, bundle)
    assert result.outcome is PutOutcome.STORED
    assert store.get(TENANT_A, _HASH) == bundle


def test_identical_content_replay_is_noop_duplicate() -> None:
    store = InMemoryEvidenceBundleStore()
    store.put(TENANT_A, _HASH, make_bundle())
    result = store.put(TENANT_A, _HASH, make_bundle())
    assert result.outcome is PutOutcome.DUPLICATE


def test_same_hash_different_content_raises_mismatch_and_never_overwrites() -> None:
    store = InMemoryEvidenceBundleStore()
    original = make_bundle(manifest={"artifacts": ["x"], "count": 1})
    store.put(TENANT_A, _HASH, original)
    collision = make_bundle(manifest={"artifacts": ["y"], "count": 2})
    with pytest.raises(EvidenceHashMismatchError) as excinfo:
        store.put(TENANT_A, _HASH, collision)
    # Content-addressing integrity: the original content is still what the
    # hash resolves to.
    assert store.get(TENANT_A, _HASH) == original
    assert excinfo.value.context["manifest_hash"] == _HASH


def test_get_absent_hash_raises_not_found() -> None:
    store = InMemoryEvidenceBundleStore()
    with pytest.raises(NotFoundError):
        store.get(TENANT_A, _OTHER_HASH)


def test_cross_tenant_same_hash_independent() -> None:
    # Content-addressed but STILL tenant-scoped: the same manifest_hash under
    # two tenants is two independent entries (a tenant must not be able to
    # read another's evidence bundle by guessing its hash).
    store = InMemoryEvidenceBundleStore()
    a = make_bundle(tenant_id=TENANT_A, manifest={"owner": "a"})
    b = make_bundle(tenant_id=TENANT_B, manifest={"owner": "b"})
    store.put(TENANT_A, _HASH, a)
    store.put(TENANT_B, _HASH, b)
    assert store.get(TENANT_A, _HASH) == a
    assert store.get(TENANT_B, _HASH) == b


def test_cross_tenant_get_is_non_leaking_absent() -> None:
    store = InMemoryEvidenceBundleStore()
    store.put(TENANT_A, _HASH, make_bundle(tenant_id=TENANT_A))
    with pytest.raises(NotFoundError):
        store.get(TENANT_B, _HASH)


def test_forged_tenant_bundle_rejected() -> None:
    store = InMemoryEvidenceBundleStore()
    forged = make_bundle(tenant_id=TENANT_B)
    with pytest.raises(TenantIsolationError):
        store.put(TENANT_A, _HASH, forged)
    with pytest.raises(NotFoundError):
        store.get(TENANT_A, _HASH)


def test_empty_tenant_rejected() -> None:
    store = InMemoryEvidenceBundleStore()
    with pytest.raises(ValueError):
        store.put("", _HASH, make_bundle())
    with pytest.raises(ValueError):
        store.get("", _HASH)


def test_empty_manifest_hash_rejected_on_put() -> None:
    # An empty content address is meaningless for a content-addressed WRITE —
    # rejected up front. A GET with an empty hash is simply a (non-leaking)
    # miss, not a validation error (a lookup never mutates state).
    store = InMemoryEvidenceBundleStore()
    with pytest.raises(ValueError):
        store.put(TENANT_A, "", make_bundle())
    with pytest.raises(NotFoundError):
        store.get(TENANT_A, "")

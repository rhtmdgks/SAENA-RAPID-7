"""`VectorRecord`/`EmbeddingMeta`/`collection_key`/`ensure_caller_owns_record`
model-level invariants (w4-07) — no I/O, no backend."""

from __future__ import annotations

import pytest
from saena_vector_store.errors import DimensionMismatchError, TenantIsolationError
from saena_vector_store.record import (
    EmbeddingMeta,
    VectorRecord,
    collection_key,
    ensure_caller_owns_record,
)
from vector_store_factories import TENANT_A, TENANT_B, embedding_meta, make_record


def test_valid_record_constructs() -> None:
    record = make_record()
    assert record.tenant_id == TENANT_A
    assert len(record.vector) == 4
    assert record.superseded is False
    assert record.superseded_by_hash is None


def test_vector_length_disagreeing_with_declared_dimension_fails_closed() -> None:
    with pytest.raises(DimensionMismatchError):
        VectorRecord(
            tenant_id=TENANT_A,
            collection="c",
            record_id="r",
            vector=(1.0, 2.0, 3.0),
            embedding=embedding_meta(dimension=4),
            source_snapshot_hash="sha256:aaa",
        )


@pytest.mark.parametrize("dimension", [0, -1, -100])
def test_embedding_meta_rejects_non_positive_dimension(dimension: int) -> None:
    with pytest.raises(DimensionMismatchError):
        EmbeddingMeta(model="m", version="1", dimension=dimension)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tenant_id": ""},
        {"collection": ""},
        {"record_id": ""},
        {"source_snapshot_hash": ""},
    ],
)
def test_empty_required_field_rejected(kwargs: dict[str, str]) -> None:
    base = {
        "tenant_id": TENANT_A,
        "collection": "c",
        "record_id": "r",
        "vector": (1.0, 0.0),
        "embedding": embedding_meta(dimension=2),
        "source_snapshot_hash": "sha256:aaa",
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        VectorRecord(**base)  # type: ignore[arg-type]


def test_collection_key_combines_tenant_and_collection() -> None:
    key_a = collection_key(TENANT_A, "claim-evidence")
    key_b = collection_key(TENANT_B, "claim-evidence")
    assert key_a != key_b
    assert TENANT_A in key_a
    assert "claim-evidence" in key_a


@pytest.mark.parametrize("tenant_id, collection", [("", "c"), ("t", ""), ("", "")])
def test_collection_key_rejects_empty_inputs(tenant_id: str, collection: str) -> None:
    with pytest.raises(ValueError):
        collection_key(tenant_id, collection)


def test_ensure_caller_owns_record_accepts_matching_tenant() -> None:
    record = make_record(tenant_id=TENANT_A)
    ensure_caller_owns_record(TENANT_A, record)  # does not raise


def test_ensure_caller_owns_record_rejects_forged_tenant_id() -> None:
    """A `VectorRecord` claiming `tenant_id=TENANT_B` presented alongside a
    caller-supplied `tenant_id=TENANT_A` is a forged-tenant-id attempt —
    every `VectorStore` backend calls this guard before any write."""
    record = make_record(tenant_id=TENANT_B)
    with pytest.raises(TenantIsolationError):
        ensure_caller_owns_record(TENANT_A, record)


def test_error_to_dict_is_structured_and_log_safe() -> None:
    record = make_record(tenant_id=TENANT_B)
    try:
        ensure_caller_owns_record(TENANT_A, record)
    except TenantIsolationError as exc:
        payload = exc.to_dict()
        assert payload["error_code"] == "saena.vector_store.tenant_isolation_violation"
        assert payload["caller_tenant_id"] == TENANT_A
        assert payload["record_tenant_id"] == TENANT_B
    else:
        pytest.fail("expected TenantIsolationError")

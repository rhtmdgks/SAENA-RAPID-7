"""Shared test-data builders for `tests/unit/vector_store` (w4-07).

Uniquely-named module (not `conftest.py`/`factories.py`) — see this
directory's `conftest.py` docstring for why: pytest's default `prepend`
import mode imports every `conftest.py` under one bare top-level `conftest`
name, so a plain `from conftest import ...` in a sibling test module
resolves to whichever directory's `conftest` Python's import cache already
holds when the FULL suite is collected together. `tests/unit/
domain_persistence/persistence_factories.py` documents this collision
first, empirically; this module sidesteps it the same way.
"""

from __future__ import annotations

from saena_vector_store.embedder import TestEmbedder
from saena_vector_store.record import EmbeddingMeta, VectorRecord

TENANT_A = "acme-co"
TENANT_B = "globex-co"

DEFAULT_COLLECTION = "claim-evidence"


def embedding_meta(*, dimension: int = 4) -> EmbeddingMeta:
    return EmbeddingMeta(model="saena-test-embedder", version="1.0.0", dimension=dimension)


def make_record(
    *,
    tenant_id: str = TENANT_A,
    collection: str = DEFAULT_COLLECTION,
    record_id: str = "doc-1",
    text: str = "hello world",
    dimension: int = 4,
    source_snapshot_hash: str = "sha256:aaa",
    seed: int = 0,
) -> VectorRecord:
    embedder = TestEmbedder(dimension=dimension, seed=seed)
    return VectorRecord(
        tenant_id=tenant_id,
        collection=collection,
        record_id=record_id,
        vector=embedder.embed_vector(text),
        embedding=embedder.embedding_meta(),
        source_snapshot_hash=source_snapshot_hash,
    )


__all__ = [
    "DEFAULT_COLLECTION",
    "TENANT_A",
    "TENANT_B",
    "embedding_meta",
    "make_record",
]

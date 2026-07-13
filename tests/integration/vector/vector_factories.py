"""Factory helpers for `tests/integration/vector` (w4-07).

Uniquely-named module (not `conftest.py`) — mirrors `tests/integration/
persistence_postgres/postgres_factories.py`'s own naming rationale (a bare
`conftest` import collides across directories once the whole `tests/` tree
is collected together). This module intentionally does NOT import from
`tests/unit/vector_store/vector_store_factories.py` (a sibling test
directory, outside this file's own subtree) to avoid the exact
cross-directory test coupling that convention warns against — it is a
small, local, one-off duplicate instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from saena_vector_store.embedder import TestEmbedder
from saena_vector_store.record import VectorRecord

TENANT_A = "acme-co"
TENANT_B = "globex-co"
DEFAULT_COLLECTION = "claim-evidence"

# Deliberately duplicated from `conftest.py`'s own `TEST_DIMENSION` (not
# imported — a plain `from conftest import ...` here would risk resolving
# to WHATEVER directory's `conftest` module Python's import cache currently
# holds once the full `tests/` suite is collected together; see this
# module's own docstring and `tests/integration/persistence_postgres/
# conftest.py`'s "Honest skip" paragraph for the fully-documented collision
# this avoids). Both values must be kept in sync; `test_pgvector_store.py`
# has its own guard test that fails loudly if they ever drift apart.
TEST_DIMENSION = 4


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


def make_record(
    *,
    tenant_id: str = TENANT_A,
    collection: str = DEFAULT_COLLECTION,
    record_id: str = "doc-1",
    text: str = "hello world",
    source_snapshot_hash: str = "sha256:aaa",
    seed: int = 0,
) -> VectorRecord:
    embedder = TestEmbedder(dimension=TEST_DIMENSION, seed=seed)
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
    "make_record",
    "run_async",
]

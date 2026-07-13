"""Edge-branch coverage (Integrator-added at w4-07 integration): the empty
`tenant_id` fail-closed guard on every InMemoryVectorStore method — the
non-integration branches the author suite left uncovered."""

from __future__ import annotations

import asyncio

import pytest
from saena_vector_store.memory import InMemoryVectorStore


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.upsert("", []),
        lambda s: s.search("", "col", (0.0,), 1),
        lambda s: s.get("", "col", "r1"),
        lambda s: s.list_versions("", "col", "r1"),
        lambda s: s.delete("", "col", ["r1"]),
        lambda s: s.invalidate_snapshot("", "col", "sha256:x"),
    ],
)
def test_empty_tenant_id_is_rejected_on_every_method(call) -> None:
    store = InMemoryVectorStore()
    with pytest.raises(ValueError, match="tenant_id is required"):
        _run(call(store))

"""Structural proof: `tenant_id` is a required, defaultless, first
positional parameter on every `VectorStore` method, on the Protocol itself
AND on both concrete backends (w4-07).

This is a signature-introspection test, not a behavioral one — it proves
there is no way to CALL any of these methods without supplying `tenant_id`
(a plain `TypeError` at the call site, before the method body ever runs),
independent of what each backend's body then does with it. Checked against
BOTH `InMemoryVectorStore` and `PgVectorStore` (import only — no engine/
connection is constructed, so this test needs no Docker/Postgres) so a
future backend added to this package inherits the same structural guarantee
by construction, not by convention.
"""

from __future__ import annotations

import inspect

import pytest
from saena_vector_store.memory import InMemoryVectorStore
from saena_vector_store.pgvector.adapter import PgVectorStore
from saena_vector_store.port import VectorStore

_TENANT_SCOPED_METHODS = (
    "upsert",
    "search",
    "get",
    "list_versions",
    "delete",
    "invalidate_snapshot",
)


def _first_param_name_and_default(fn: object) -> tuple[str, object]:
    signature = inspect.signature(fn)  # type: ignore[arg-type]
    params = list(signature.parameters.values())
    # params[0] is `self` for a bound-less function pulled off a class.
    assert params[0].name == "self"
    first = params[1]
    return first.name, first.default


@pytest.mark.parametrize("method_name", _TENANT_SCOPED_METHODS)
def test_protocol_declares_tenant_id_as_defaultless_first_param(method_name: str) -> None:
    fn = getattr(VectorStore, method_name)
    name, default = _first_param_name_and_default(fn)
    assert name == "tenant_id"
    assert default is inspect.Parameter.empty


@pytest.mark.parametrize("method_name", _TENANT_SCOPED_METHODS)
def test_in_memory_store_declares_tenant_id_as_defaultless_first_param(method_name: str) -> None:
    fn = getattr(InMemoryVectorStore, method_name)
    name, default = _first_param_name_and_default(fn)
    assert name == "tenant_id"
    assert default is inspect.Parameter.empty


@pytest.mark.parametrize("method_name", _TENANT_SCOPED_METHODS)
def test_pgvector_store_declares_tenant_id_as_defaultless_first_param(method_name: str) -> None:
    fn = getattr(PgVectorStore, method_name)
    name, default = _first_param_name_and_default(fn)
    assert name == "tenant_id"
    assert default is inspect.Parameter.empty


def test_in_memory_store_satisfies_vector_store_protocol() -> None:
    """Cheap regression guard (method-name presence only, mirrors
    `tests/unit/domain_persistence/test_ports_conformance.py`'s own
    `isinstance`-against-`runtime_checkable`-Protocol convention) — full
    signature compatibility is covered by `just typecheck` (mypy structural
    check), not by this runtime check."""
    assert isinstance(InMemoryVectorStore(), VectorStore)


def test_calling_upsert_without_tenant_id_is_a_type_error() -> None:
    """Behavioral confirmation of the structural guarantee above: calling
    `upsert` with a records-only argument (omitting `tenant_id` entirely,
    not even via keyword) is a plain `TypeError`, not a silent
    "any tenant" default."""
    store = InMemoryVectorStore()
    with pytest.raises(TypeError):
        store.upsert(records=())  # type: ignore[call-arg]

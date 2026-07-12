"""Factory helpers for `saena_domain.persistence.postgres` integration tests.

Deliberately not named `conftest.py`'s own module surface, mirroring
`tests/unit/domain_persistence/persistence_factories.py`'s own naming
rationale (avoiding a `conftest`-module import collision when the full
`tests/` suite is collected together) — this module is a LOCAL duplicate of
that sibling package's factory helpers (not an import from it: `tests/unit/
domain_persistence/**` is outside this patch unit's exclusive write paths,
and importing across sibling test packages would create exactly the kind of
cross-directory test coupling that module's own docstring documents as
previously having caused a real collision).

`run_async` also lives here (rather than in this package's OWN
`conftest.py`) for the identical reason — see `conftest.py`'s own docstring
"Honest skip" paragraph for the full explanation of why a plain `from
conftest import run_async` breaks once the whole `tests/` suite is
collected together.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from saena_domain.audit.chain import build_entry
from saena_domain.events import EnvelopeFactory
from saena_domain.identity import TenantContext

TENANT_A = "acme-co"
TENANT_B = "globex-co"


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine to completion — plain `asyncio.run`, no pytest-asyncio
    plugin is installed in this workspace (see `tests/unit/domain_identity/
    test_execution_context.py`'s own `asyncio.run(scenario())` precedent).
    Every test module in this package drives its async work through this
    helper — see `conftest.py`'s module docstring for why it is defined
    here rather than in `conftest.py` itself."""
    return asyncio.run(coro)


def make_tenant_context_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "display_name": "Acme Co",
        "isolation_profile": "internal-k3s",
        "namespace": "saena-tenant-acme-co",
        "policy_version": "1.0.0",
        "engine_scope": ["chatgpt-search"],
        "status": "active",
        "retention_policy_ref": "retention-policy-default",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def make_tenant_context(**overrides: Any) -> TenantContext:
    return TenantContext.from_payload(make_tenant_context_payload(**overrides))


def make_audit_entry(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "prev_hash": None,
        "action": "patch.unit.completed.v1",
        "recorded_at": "2026-07-12T09:14:32Z",
        "scope": "tenant",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "payload": {"patch_unit_id": "w2-13-postgres"},
        "tenant_id": TENANT_A,
        "run_id": "run-2026-0712-0013",
    }
    base.update(overrides)
    prev_hash = base["prev_hash"]
    if prev_hash is not None and not isinstance(prev_hash, str):
        base["prev_hash"] = prev_hash.root
    return build_entry(**base)


def make_tenant_envelope(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "producer": "agent-runner-service",
        "event_type": "patch.unit.completed.v1",
        "tenant_id": TENANT_A,
        "run_id": "run-2026-0712-0013",
        "idempotency_key": "acme-co:run-2026-0712-0013:patch-unit-042",
        "payload": {"patch_unit_id": "w2-13-postgres", "worktree_commit": "9f1c2e7"},
    }
    base.update(overrides)
    return EnvelopeFactory.build_tenant_envelope(**base)


def make_system_envelope(**overrides: Any) -> dict[str, Any]:
    """See `tests/unit/domain_persistence/persistence_factories.py`'s own
    `make_system_envelope` docstring for the by-hand reshape rationale
    (v1 CONFIRMED AsyncAPI catalog has zero `context_type: system`
    channels)."""
    base = make_tenant_envelope(
        event_type=overrides.pop("event_type", "patch.unit.completed.v1"),
        idempotency_key=overrides.pop("idempotency_key", "system:adapter-config:v1.3.0"),
    )
    base.pop("tenant_id", None)
    base.pop("run_id", None)
    base["context_type"] = "system"
    base.update(overrides)
    return base

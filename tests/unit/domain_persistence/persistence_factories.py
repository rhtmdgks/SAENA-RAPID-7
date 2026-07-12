"""Factory helpers for `saena_domain.persistence` unit tests.

Deliberately NOT named `conftest.py`'s own module surface — pytest's default
`prepend` import mode (`--import-mode` is unset in `pyproject.toml`) inserts
each directory containing a `conftest.py` onto `sys.path` and imports it
under the bare top-level name `conftest`; a SECOND directory doing
`from conftest import ...` while ALSO having its own `conftest.py` collides
with whichever `conftest` module Python's import cache already holds when
the full `tests/unit` suite is collected together (proven empirically: this
directory previously named this module `conftest.py` and
`tests/unit/domain_identity/conftest.py`'s own factories shadowed it,
`ImportError: cannot import name 'make_audit_entry' from 'conftest'`, when
both directories were collected in the same pytest run). This module is
imported by its own unique dotted name
(`persistence_factories`, inserted onto `sys.path` by `conftest.py` in this
same directory) to avoid that collision entirely.
"""

from __future__ import annotations

from typing import Any

from saena_domain.audit.chain import build_entry
from saena_domain.events import EnvelopeFactory
from saena_domain.identity import TenantContext

TENANT_A = "acme-co"
TENANT_B = "globex-co"


def make_tenant_context_payload(**overrides: Any) -> dict[str, Any]:
    """Schema-valid `TenantContext` payload, mirrors
    `tests/unit/domain_identity/conftest.py::make_tenant_context_payload`."""
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
    """A guarded, hash-linked `AuditEntry` with GENESIS prev_hash by default.

    `prev_hash`, if given, may be a plain `str` or the generated `Sha256Ref`
    root-model wrapper (e.g. a prior entry's `.event_hash`) — this helper
    unwraps it, mirroring `saena_domain.audit.chain`'s own `_plain_str`
    handling, since callers naturally have a previous `AuditEntry.event_hash`
    (a `Sha256Ref`) on hand, not a pre-unwrapped string.
    """
    base: dict[str, Any] = {
        "prev_hash": None,
        "action": "patch.unit.completed.v1",
        "recorded_at": "2026-07-12T09:14:32Z",
        "scope": "tenant",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "payload": {"patch_unit_id": "w2-07-persistence"},
        "tenant_id": TENANT_A,
        "run_id": "run-2026-0712-0007",
    }
    base.update(overrides)
    prev_hash = base["prev_hash"]
    if prev_hash is not None and not isinstance(prev_hash, str):
        base["prev_hash"] = prev_hash.root
    return build_entry(**base)


def make_tenant_envelope(**overrides: Any) -> dict[str, Any]:
    """A valid `context_type: tenant` envelope via the real `EnvelopeFactory`."""
    base: dict[str, Any] = {
        "producer": "agent-runner-service",
        "event_type": "patch.unit.completed.v1",
        "tenant_id": TENANT_A,
        "run_id": "run-2026-0712-0007",
        "idempotency_key": "acme-co:run-2026-0712-0007:patch-unit-042",
        "payload": {"patch_unit_id": "w2-07-persistence", "worktree_commit": "9f1c2e7"},
    }
    base.update(overrides)
    return EnvelopeFactory.build_tenant_envelope(**base)


def make_system_envelope(**overrides: Any) -> dict[str, Any]:
    """A schema-valid `context_type: system` envelope, built BY HAND rather
    than via `EnvelopeFactory.build_system_envelope`.

    The v1 CONFIRMED AsyncAPI catalog carries zero `context_type: system`
    channels (`saena_domain.events.factory` module docstring's own "Catalog
    gap note") — `build_system_envelope` can only be exercised against a
    private, test-only fixture catalog belonging to `tests/unit/
    domain_events` (outside this unit's exclusive-write paths). This helper
    instead starts from a valid tenant envelope (via the real
    `EnvelopeFactory`, so every OTHER field is genuinely schema-valid) and
    reshapes it to `context_type: system` by hand — `tenant_id`/`run_id`
    dropped, matching the envelope contract's own system-context shape
    (ADR-0013). Good enough for `saena_domain.persistence`'s own envelope
    dual-validation and tenant-scoping tests, which only need a
    schema-valid, `tenant_id`-absent envelope — they do not exercise
    `EnvelopeFactory`'s AsyncAPI topic/producer resolution at all.
    """
    base = make_tenant_envelope(
        event_type=overrides.pop("event_type", "patch.unit.completed.v1"),
        idempotency_key=overrides.pop("idempotency_key", "system:adapter-config:v1.3.0"),
    )
    base.pop("tenant_id", None)
    base.pop("run_id", None)
    base["context_type"] = "system"
    base.update(overrides)
    return base

"""Shared fixtures/factories for `saena_domain.identity` unit tests.

`tests/` is not a package (no `tests/__init__.py`, mirroring the existing
`tests/contract` convention — see tests/contract/conftest.py). Test modules
in this directory import helpers via a bare `from conftest import ...`, which
requires this directory itself to be on `sys.path`; pytest's rootdir-relative
conftest collection does not guarantee that on its own, so it is inserted
explicitly here, once, before any sibling test module is collected.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))


def make_tenant_context_payload(**overrides: Any) -> dict[str, Any]:
    """A schema-valid `TenantContext` payload (mirrors
    tests/contract/fixtures/tenant-context/valid/active-tenant.json),
    overridable per test.
    """
    payload: dict[str, Any] = {
        "tenant_id": "acme-corp",
        "display_name": "Acme Corp",
        "isolation_profile": "internal-k3s",
        "namespace": "saena-tenant-acme-corp",
        "policy_version": "1.0.0",
        "engine_scope": ["chatgpt-search"],
        "status": "active",
        "retention_policy_ref": "retention-policy-default",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def make_actor_context_payload(**overrides: Any) -> dict[str, Any]:
    """A schema-valid `ActorContext` payload (system actor, no tenant_id by
    default — mirrors
    tests/contract/fixtures/actor-context/valid/system-actor-no-tenant.json).
    """
    payload: dict[str, Any] = {
        "actor_id": "actor-system-worker-0001",
        "actor_type": "system",
        "session_id": "session-example-0002",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def tenant_context_payload() -> dict[str, Any]:
    return make_tenant_context_payload()


@pytest.fixture
def actor_context_payload() -> dict[str, Any]:
    return make_actor_context_payload()

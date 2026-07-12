"""Shared fixtures for `saena_forge_console` unit tests.

`tests/` is not a package (no `tests/__init__.py` at the root — mirrors
`tests/contract/conftest.py` / `tests/unit/domain_identity/conftest.py`).
This directory has its own `__init__.py` (matching
`tests/unit/domain_persistence`'s convention, another `tests/unit/*`
subpackage) so pytest resolves this module's imports as
`svc_forge_console.conftest` without needing a `sys.path` insert.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from saena_forge_console.app import create_app
from saena_forge_console.lineage import InMemoryLineagePort
from saena_forge_console.run_store import RunStore

DEFAULT_TENANT = "acme-corp"
OTHER_TENANT = "other-corp"


def actor_headers(
    *,
    actor_id: str = "actor-0001",
    session_id: str = "session-0001",
    actor_type: str = "human",
    tenant_id: str | None = DEFAULT_TENANT,
    roles: str | None = None,
) -> dict[str, str]:
    """Build request headers for `saena_forge_console.authn.build_request_actor`."""
    headers: dict[str, str] = {
        "X-Saena-Actor-Id": actor_id,
        "X-Saena-Session-Id": session_id,
        "X-Saena-Actor-Type": actor_type,
    }
    if tenant_id is not None:
        headers["X-Saena-Tenant-Id"] = tenant_id
    if roles is not None:
        headers["X-Saena-Roles"] = roles
    return headers


def run_create_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "state": "INTAKE",
        "base_commit": "a" * 40,
        "human_approval_required": True,
    }
    body.update(overrides)
    return body


@pytest.fixture
def lineage_port() -> InMemoryLineagePort:
    return InMemoryLineagePort()


@pytest.fixture
def run_store() -> RunStore:
    return RunStore()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    run_store: RunStore,
    lineage_port: InMemoryLineagePort,
) -> TestClient:
    """A `TestClient` wired against a fresh app per test, with
    `SAENA_TENANT_ID` set to `DEFAULT_TENANT` so the tenant-reconciliation
    middleware's pod-env side matches `actor_headers()`'s default tenant
    header out of the box. Tests exercising a MISMATCH override the header
    (or the env var) explicitly per test.
    """
    monkeypatch.setenv("SAENA_TENANT_ID", DEFAULT_TENANT)
    app = create_app(run_store=run_store, lineage_port=lineage_port)
    return TestClient(app)


__all__ = [
    "DEFAULT_TENANT",
    "OTHER_TENANT",
    "actor_headers",
    "run_create_body",
]

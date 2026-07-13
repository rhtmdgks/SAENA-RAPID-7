"""Shared fixtures for `saena_engine_gateway` unit tests.

`tests/` is not a package (no `tests/__init__.py`, mirroring the existing
`tests/contract`/`tests/unit/domain_identity` convention — see
`tests/unit/domain_identity/conftest.py`). Test modules in this directory
import helpers via a bare `from conftest import ...`, which requires this
directory itself to be on `sys.path`; inserted explicitly here, once,
before any sibling test module is collected.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from saena_engine_gateway.adapters.chatgpt_search import ChatGPTSearchAdapter
from saena_engine_gateway.app import create_app
from saena_engine_gateway.flags import FlagRegistry
from saena_engine_gateway.registry import AdapterRegistry

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

TENANT_ID = "acme-corp"
TENANT_HEADERS = {"X-Saena-Tenant-Id": TENANT_ID}


@pytest.fixture
def _bound_tenant_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Bind `SAENA_TENANT_ID` for the duration of a test (ADR-0014 pod env
    var side of the reconciliation check)."""
    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_ID)
    yield


@pytest.fixture
def default_registry() -> AdapterRegistry:
    """A v1-standard registry: `ChatGPTSearchAdapter` registered."""
    registry = AdapterRegistry()
    registry.register(ChatGPTSearchAdapter())
    return registry


@pytest.fixture
def default_flags() -> FlagRegistry:
    """A v1-standard flag registry: `chatgpt-search` enabled."""
    flags = FlagRegistry()
    flags.create("chatgpt-search", enabled=True)
    return flags


@pytest.fixture
def client(
    _bound_tenant_env: None,
    default_registry: AdapterRegistry,
    default_flags: FlagRegistry,
) -> TestClient:
    """A `TestClient` over the v1-standard app (ChatGPT Search registered
    and enabled), with `SAENA_TENANT_ID` bound to match `TENANT_HEADERS`."""
    app = create_app(registry=default_registry, flags=default_flags)
    return TestClient(app)


@pytest.fixture
def flag_off_client(_bound_tenant_env: None, default_registry: AdapterRegistry) -> TestClient:
    """A `TestClient` where `chatgpt-search` is registered but its flag is
    off — for exercising `AdapterDisabledError` / policy_denied."""
    flags = FlagRegistry()
    flags.create("chatgpt-search", enabled=False)
    app = create_app(registry=default_registry, flags=flags)
    return TestClient(app)


@pytest.fixture
def empty_client(_bound_tenant_env: None) -> TestClient:
    """A `TestClient` with nothing registered and nothing flagged — for
    exercising the empty-registry / not-found path."""
    app = create_app(registry=AdapterRegistry(), flags=FlagRegistry())
    return TestClient(app)

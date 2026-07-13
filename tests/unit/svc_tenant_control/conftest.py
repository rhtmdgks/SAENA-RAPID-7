"""pytest fixtures for `tests/unit/svc_tenant_control`.

Mirrors the `tests/unit/domain_persistence` convention: `tests/` is not a
package, so this directory is inserted onto `sys.path` for sibling test
modules to import shared factory helpers by dotted name
(`tenant_control_factories`, not this module — see that module's own
docstring for why).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from saena_domain.identity import TENANT_ENV_VAR_NAME  # noqa: E402
from saena_domain.persistence import InMemoryOutbox, InMemoryTenantRepository  # noqa: E402
from saena_tenant_control import create_app  # noqa: E402
from tenant_control_factories import TENANT_A  # noqa: E402


@pytest.fixture
def repo() -> InMemoryTenantRepository:
    return InMemoryTenantRepository()


@pytest.fixture
def outbox() -> InMemoryOutbox:
    return InMemoryOutbox()


@pytest.fixture
def client(
    repo: InMemoryTenantRepository, outbox: InMemoryOutbox, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setenv(TENANT_ENV_VAR_NAME, TENANT_A)
    app = create_app(repo, outbox)
    return TestClient(app)

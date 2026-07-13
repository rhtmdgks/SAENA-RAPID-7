"""pytest fixtures for `tests/unit/domain_bus`.

Same `sys.path` insertion pattern as `tests/unit/domain_persistence/
conftest.py` — this directory is inserted onto `sys.path` so sibling test
modules can `from bus_factories import ...` under a uniquely-named module
(see that module's own docstring for the import-collision rationale).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from bus_factories import TENANT_A, TENANT_B  # noqa: E402
from saena_domain.identity import TenantId  # noqa: E402


@pytest.fixture
def tenant_id() -> TenantId:
    return TenantId(TENANT_A)


@pytest.fixture
def other_tenant_id() -> TenantId:
    return TenantId(TENANT_B)

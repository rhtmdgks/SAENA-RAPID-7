"""pytest fixtures for `tests/unit/svc_audit_ledger`.

`tests/` is not a package (no `tests/__init__.py`, matching
`tests/unit/domain_persistence`'s own convention) — this directory is
inserted onto `sys.path` so sibling test modules can
`from ledger_factories import ...` (see that module's docstring, and
`tests/unit/domain_persistence/persistence_factories.py`'s own docstring for
why a uniquely-named factory module — not another `conftest.py` — is used to
avoid an `--import-mode=prepend` collision when the whole `tests/unit` tree
is collected together).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from saena_audit_ledger import create_app  # noqa: E402
from saena_domain.persistence import InMemoryAuditLedger  # noqa: E402


@pytest.fixture
def ledger() -> InMemoryAuditLedger:
    return InMemoryAuditLedger()


@pytest.fixture
def client(ledger: InMemoryAuditLedger) -> TestClient:
    return TestClient(create_app(ledger))

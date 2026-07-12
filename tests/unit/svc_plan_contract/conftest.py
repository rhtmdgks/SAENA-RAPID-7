"""pytest fixtures for `tests/unit/svc_plan_contract`.

`tests/` is not a package — this directory is inserted onto `sys.path` so
sibling test modules can `from plan_contract_factories import ...` (see
`persistence_factories.py`'s own docstring, `tests/unit/domain_persistence/`,
for why factory helpers live under a uniquely-named module rather than a
bare `conftest` name: multiple `conftest.py` files across `tests/unit/*`
collide under pytest's default import mode if two directories both try to
export from a module literally named `conftest`).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from plan_contract_factories import TENANT_ID, load_change_plan_fixture  # noqa: E402
from saena_domain.persistence import InMemoryOutbox, InMemoryPlanRepository  # noqa: E402
from saena_plan_contract import create_app  # noqa: E402
from saena_plan_contract.audit_trail import AuditTrailStore  # noqa: E402
from saena_plan_contract.gate_client import FakeGateClient  # noqa: E402


@pytest.fixture
def plans() -> InMemoryPlanRepository:
    return InMemoryPlanRepository()


@pytest.fixture
def outbox() -> InMemoryOutbox:
    return InMemoryOutbox()


@pytest.fixture
def audit_trail() -> AuditTrailStore:
    return AuditTrailStore()


@pytest.fixture
def gate() -> FakeGateClient:
    return FakeGateClient()


@pytest.fixture
def app_factory(plans, outbox, gate, audit_trail):
    """Returns a callable so a test can override `gate.mode` before building
    the app (the app closes over the SAME `gate`/`plans`/`outbox` objects
    passed in, so mutating `gate.mode` after `create_app` still takes effect
    on the next request — `FakeGateClient.plan_check` reads `self.mode` at
    call time, not at construction time)."""

    def _build():
        return create_app(
            plans=plans,
            outbox=outbox,
            gate=gate,
            audit_trail=audit_trail,
            tenant_env_value=TENANT_ID,
        )

    return _build


@pytest.fixture
def client(app_factory) -> TestClient:
    return TestClient(app_factory())


@pytest.fixture
def headers() -> dict[str, str]:
    return {"X-Saena-Tenant-Id": TENANT_ID, "X-Saena-Actor-Id": "actor-proposer-0001"}


@pytest.fixture
def change_plan() -> dict[str, object]:
    return load_change_plan_fixture("single-patch-unit.json", tenant_id=TENANT_ID)

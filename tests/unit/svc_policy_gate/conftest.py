"""pytest fixtures for `tests/unit/svc_policy_gate`.

Mirrors the `tests/unit/domain_persistence` convention (module docstring
there explains why factory helpers live in a sibling non-`conftest`-named
module rather than here): this directory is inserted onto `sys.path` so test
modules can `from policy_gate_factories import ...`.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from saena_domain.identity import TenantId  # noqa: E402
from saena_domain.persistence.memory import InMemoryDecisionRecordStore  # noqa: E402
from saena_domain.persistence.ports import DecisionRecordPort  # noqa: E402
from saena_policy_gate.app import create_app, get_decision_store, get_engine  # noqa: E402
from saena_policy_gate.engine import PolicyEngine  # noqa: E402
from saena_policy_gate.rules import default_engine_rules  # noqa: E402

TENANT_A = "acme-co"
TENANT_B = "globex-co"


@pytest.fixture
def tenant_id() -> TenantId:
    return TenantId(TENANT_A)


@pytest.fixture
def decision_store() -> DecisionRecordPort:
    return InMemoryDecisionRecordStore()


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine(default_engine_rules())


@pytest.fixture
def client(decision_store: DecisionRecordPort, engine: PolicyEngine) -> Iterator[TestClient]:
    """A `TestClient` wired to fresh, per-test store/engine instances (never
    the module-level singletons in `saena_policy_gate.app`, so tests never
    leak decision-store state into one another)."""
    app = create_app()
    app.dependency_overrides[get_decision_store] = lambda: decision_store
    app.dependency_overrides[get_engine] = lambda: engine
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def tenant_headers() -> Iterator[dict[str, str]]:
    """Sets `SAENA_TENANT_ID=acme-co` for the test's duration and returns
    the matching `X-Saena-Tenant-Id` request header dict."""
    prior = os.environ.get("SAENA_TENANT_ID")
    os.environ["SAENA_TENANT_ID"] = TENANT_A
    try:
        yield {"X-Saena-Tenant-Id": TENANT_A}
    finally:
        if prior is None:
            os.environ.pop("SAENA_TENANT_ID", None)
        else:
            os.environ["SAENA_TENANT_ID"] = prior

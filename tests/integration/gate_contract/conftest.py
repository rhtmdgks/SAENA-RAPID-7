"""pytest fixtures for `tests/integration/gate_contract`.

`tests/` is not a package — this directory is inserted onto `sys.path` so
sibling test modules can `from gate_contract_factories import ...` (same
pattern `tests/unit/svc_plan_contract/conftest.py` and
`tests/integration/approval_flow/conftest.py` already use — see either
module's own docstring for why factory helpers live under a uniquely-named
module rather than a bare `conftest` name).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from gate_contract_factories import TENANT_ID  # noqa: E402
from saena_plan_contract.gate_client import HttpPolicyGateClient  # noqa: E402
from saena_policy_gate.app import create_app  # noqa: E402


@pytest.fixture
def policy_gate_app_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The real `policy-gate-service` ASGI app behind a `TestClient` — its
    own `httpx.Client`-compatible transport is what `real_gate_client` below
    injects into `HttpPolicyGateClient` (see package docstring for why
    `TestClient`, not a bare `httpx.Client(transport=ASGITransport(...))`).

    `TenantHeaderMiddleware` reconciles `X-Saena-Tenant-Id` against the
    `SAENA_TENANT_ID` process env var AT REQUEST TIME (`tenant_middleware.py`
    — same pattern `tests/integration/approval_flow/conftest.py` already
    handles for this same service) — `monkeypatch.setenv` so pytest restores
    the prior value at teardown even on failure.
    """
    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_ID)
    app = create_app()
    with TestClient(app, base_url="http://policy-gate") as client:
        yield client


@pytest.fixture
def real_gate_client(policy_gate_app_client: TestClient) -> Iterator[HttpPolicyGateClient]:
    """`HttpPolicyGateClient`, UNMODIFIED constructor/signature, wired to
    the real policy-gate app's own transport — proves the production client
    code path (path, request shape, response parse), not a test double."""
    client = HttpPolicyGateClient("http://policy-gate", client=policy_gate_app_client, timeout=5.0)
    yield client
    client.close()

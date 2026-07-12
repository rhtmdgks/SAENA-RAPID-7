"""pytest fixtures for `tests/integration/approval_flow` (and reused by
`tests/e2e/approval`, which inserts THIS directory onto `sys.path` — see
that package's own `conftest.py`).

`tests/` is not a package — this directory is inserted onto `sys.path` so
sibling test modules can `from approval_harness import ...` / `from approval_factories
import ...` (see `tests/unit/svc_plan_contract/conftest.py`'s own docstring
for why factory/harness helpers live under uniquely-named modules rather
than a bare `conftest` name — multiple `conftest.py` files across the repo
collide under pytest's default `prepend` import mode if two directories both
export from a module literally named `conftest`).

Every fixture here sets `SAENA_TENANT_ID` via `monkeypatch.setenv` (never a
raw `os.environ[...] = ...` assignment) so pytest restores the prior value
automatically at teardown, even on failure — `forge-console-api` and
`policy-gate-service` both reconcile `X-Saena-Tenant-Id` against this process
env var AT REQUEST TIME (`tenant_reconcile.py` / `tenant_middleware.py`),
not at app-construction time; `plan-contract-service` is the one exception
(`tenant_env_value` is a `create_app(...)` PARAMETER baked into
`app.state` once, per that module's own docstring) — tests that need a
plan-contract app pinned to a SPECIFIC tenant build a dedicated harness for
it (`harness.build_harness(tenant_id=...)`), while forge-console/policy-gate
reconciliation can be flipped per-request via `monkeypatch.setenv` against
the SAME already-built app.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from approval_factories import TENANT_A, load_change_plan_fixture  # noqa: E402
from approval_harness import (  # noqa: E402
    ApprovalFlowHarness,
    build_fail_closed_harness,
    build_harness,
)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> ApprovalFlowHarness:
    """The primary wired harness: real policy-gate-service HTTP surface via
    `PlanContractHttpGateAdapter`, shared in-memory persistence, `TENANT_A`
    pinned as both plan-contract's `tenant_env_value` and the process
    `SAENA_TENANT_ID` env var (forge-console/policy-gate's own
    reconciliation target).
    """
    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_A)
    built = build_harness(tenant_id=TENANT_A)
    yield built
    built.close()


@pytest.fixture
def fail_closed_harness(monkeypatch: pytest.MonkeyPatch) -> ApprovalFlowHarness:
    """The W2A exit fail-closed-demo harness — plan-contract's gate port is
    wired to `DownPolicyGateClient` (a REAL, but broken, policy-gate-shaped
    HTTP surface) instead of a working `policy-gate-service` app."""
    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_A)
    built = build_fail_closed_harness(tenant_id=TENANT_A)
    yield built
    built.close()


@pytest.fixture
def proposer_headers() -> dict[str, str]:
    return {"X-Saena-Tenant-Id": TENANT_A, "X-Saena-Actor-Id": "actor-proposer-0001"}


@pytest.fixture
def change_plan() -> dict[str, object]:
    return load_change_plan_fixture("single-patch-unit.json", tenant_id=TENANT_A)

"""pytest fixtures for `tests/e2e/approval` — reuses
`tests/integration/approval_flow`'s harness/factories rather than
duplicating them (single source of truth for how the four W2A service apps
are wired together).

`tests/` is not a package — both this directory AND
`tests/integration/approval_flow` are inserted onto `sys.path` so this
package's test modules can `from approval_harness import ...` / `from
approval_factories import ...` the SAME way `tests/integration/approval_flow`
itself does (see that package's `conftest.py` docstring for the full
rationale on uniquely-named modules avoiding the `--import-mode=prepend`
`conftest` collision).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_INTEGRATION_HARNESS_DIR = _THIS_DIR.parents[1] / "integration" / "approval_flow"

for _dir in (_THIS_DIR, _INTEGRATION_HARNESS_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import pytest  # noqa: E402
from approval_factories import TENANT_A, load_change_plan_fixture  # noqa: E402
from approval_harness import (  # noqa: E402
    ApprovalFlowHarness,
    build_fail_closed_harness,
    build_harness,
)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> ApprovalFlowHarness:
    monkeypatch.setenv("SAENA_TENANT_ID", TENANT_A)
    built = build_harness(tenant_id=TENANT_A)
    yield built
    built.close()


@pytest.fixture
def fail_closed_harness(monkeypatch: pytest.MonkeyPatch) -> ApprovalFlowHarness:
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

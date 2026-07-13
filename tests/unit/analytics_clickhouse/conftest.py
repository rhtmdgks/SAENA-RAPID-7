"""pytest fixtures for `tests/unit/analytics_clickhouse` (w4-06).

Inserts this directory onto `sys.path` so sibling test modules can
`from analytics_clickhouse_factories import ...` — see that module's own
docstring for why factory helpers live there rather than under a bare
`conftest` name.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from analytics_clickhouse_factories import (  # noqa: E402
    TENANT_A,
    TENANT_B,
    FakeClickHouseExecutor,
    new_fake_executor_with_tables,
)
from saena_analytics_clickhouse.store import ClickHouseAnalyticsStore  # noqa: E402


@pytest.fixture
def tenant_id() -> str:
    return TENANT_A


@pytest.fixture
def other_tenant_id() -> str:
    return TENANT_B


@pytest.fixture
def fake_executor() -> FakeClickHouseExecutor:
    return new_fake_executor_with_tables()


@pytest.fixture
def store(fake_executor: FakeClickHouseExecutor) -> ClickHouseAnalyticsStore:
    return ClickHouseAnalyticsStore(fake_executor)

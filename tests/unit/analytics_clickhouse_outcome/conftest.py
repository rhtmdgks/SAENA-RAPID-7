"""pytest fixtures for `tests/unit/analytics_clickhouse_outcome` (w5-11).

Inserts this directory onto `sys.path` so sibling test modules can
`from analytics_clickhouse_outcome_factories import ...` — same convention as
`tests/unit/analytics_clickhouse/conftest.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from analytics_clickhouse_outcome_factories import (  # noqa: E402
    TENANT_A,
    TENANT_B,
    FakeClickHouseExecutor,
    new_fake_executor_with_outcome_table,
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
    return new_fake_executor_with_outcome_table()


@pytest.fixture
def store(fake_executor: FakeClickHouseExecutor) -> ClickHouseAnalyticsStore:
    return ClickHouseAnalyticsStore(fake_executor)

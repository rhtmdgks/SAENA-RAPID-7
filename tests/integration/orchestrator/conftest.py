"""pytest fixtures for `tests/integration/orchestrator`.

Registers the `integration` marker locally (this test directory is this
patch unit's exclusive write path; the root `pyproject.toml`
`[tool.pytest.ini_options]` markers list is NOT — no other patch unit has
registered a marker there yet, so this conftest's own `pytest_configure`
hook is the only in-scope place to do it without touching root config).

Also inserts `tests/unit/svc_orchestrator` (this same patch unit's other
exclusive-write test directory) onto `sys.path` so this module can reuse
`orchestrator_factories` rather than duplicating fixture-payload
construction across both test trees.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_UNIT_TEST_FACTORIES_DIR = Path(__file__).resolve().parents[2] / "unit" / "svc_orchestrator"

if str(_UNIT_TEST_FACTORIES_DIR) not in sys.path:
    sys.path.insert(0, str(_UNIT_TEST_FACTORIES_DIR))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: exercises a real Temporal test-server process "
        "(temporalio.testing.WorkflowEnvironment.start_time_skipping); "
        "may be skipped when the test-server binary is unavailable.",
    )

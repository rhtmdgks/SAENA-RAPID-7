"""pytest fixtures for ``tests/integration/measurement_workflow``.

Registers the ``integration`` marker locally (harmless redundancy with the root
registration — same note as ``tests/integration/orchestrator/conftest.py``) and
bridges ``sys.path`` so the not-yet-installed service package
(``saena_experiment_attribution``) and the shared ``attribution_factories``
(under ``tests/unit/svc_experiment_attribution_workflow``) both import — the same
cross-lane ``sys.path`` reuse the orchestrator integration conftest does for its
factory dir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SVC_SRC = _REPO_ROOT / "services" / "experimentation" / "experiment-attribution-service" / "src"
_UNIT_FACTORIES_DIR = _REPO_ROOT / "tests" / "unit" / "svc_experiment_attribution_workflow"
_INTEGRATION_DIR = _REPO_ROOT / "tests" / "integration"

for _path in (_INTEGRATION_DIR, _SVC_SRC, _UNIT_FACTORIES_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: exercises a real Temporal test-server process "
        "(temporalio.testing.WorkflowEnvironment.start_time_skipping); "
        "may be skipped when the test-server binary is unavailable.",
    )

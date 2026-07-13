"""pytest fixtures for `tests/unit/evals_harness` (w3-10).

Inserts THIS directory onto `sys.path` FIRST (before any sibling
`test_*.py` module is imported by pytest) so `import harness_paths` — a
uniquely-named sibling module, never a second `conftest.py`, see its own
docstring — resolves as a bare top-level import from every test module in
this directory, mirroring `tests/unit/svc_agent_runner/conftest.py`'s own
proven pattern. `harness_paths` itself then inserts the repo root onto
`sys.path` so `evals.engine.*` imports as a real, dotted Python package
(`evals/` is a plain directory tree, not a `[tool.uv.workspace]` member —
root `pyproject.toml` is outside this patch unit's exclusive write paths).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pytest  # noqa: E402
from harness_paths import AXIS_FIXTURE_DIRS, REPO_ROOT  # noqa: E402


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def axis_fixture_dirs() -> dict[str, Path]:
    return AXIS_FIXTURE_DIRS

"""pytest fixtures/sys.path wiring for `tests/e2e/measurement` (w5-19/c5-01).

Mirrors `tests/e2e/intelligence/conftest.py`: `tests/` is not a package, so
`measurement_e2e_harness.py` needs to be `import`-able BY NAME from this
directory's own test modules AND from `tests/integration/measurement_e2e/**`
(the real-container companion lane reuses this SAME harness so both lanes
build from byte-identical synthetic input — see that harness module's own
docstring). Every `saena_*` package this suite exercises via `packages/`
is already a registered `uv` workspace member; `saena_experiment_attribution`
and `saena_strategy_skill_bank` are NOT (yet) registered workspace members
(see their own `pyproject.toml` NOTE, same as `tests/integration/
measurement_pg/conftest.py`), so their `src/` dirs are inserted onto
`sys.path` directly here too — this lane exercises the real service
boundary/pipeline/publisher code, not a stand-in.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_ATTRIBUTION_SRC = (
    _REPO_ROOT / "services" / "experimentation" / "experiment-attribution-service" / "src"
)
_SKILL_BANK_SRC = (
    _REPO_ROOT / "services" / "experimentation" / "strategy-skill-bank-service" / "src"
)

for _path in (_THIS_DIR, _ATTRIBUTION_SRC, _SKILL_BANK_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: exercises real out-of-process infrastructure "
        "(Docker containers and/or a Temporal test-server process); "
        "may be skipped when that infrastructure is genuinely unavailable "
        "(ADR-0017 honest-skip discipline) — see this directory's own "
        "collection guard for the zero-collected hard-failure exception.",
    )

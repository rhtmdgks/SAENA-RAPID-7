"""Shared path constants for `tests/unit/evals_harness` test modules.

Deliberately NOT named `conftest.py` and NOT imported as `from conftest
import ...` by sibling test modules: a same-named `conftest` module
collision across test directories has bitten this repo before when a full
multi-directory `pytest` run is collected together (a bare `import conftest`
resolves to whichever `conftest.py` module Python's import system loaded
FIRST under that name, not necessarily this directory's own) — see e.g.
`tests/unit/svc_artifact_registry/registry_factories.py`'s own docstring
precedent. This module's job is exactly what `_support.py`/`*_factories.py`
siblings do elsewhere in this repo: hold the plain constants, imported by
BOTH this directory's `conftest.py` (for pytest fixture registration) and
every `test_*.py` module here, under one unique bare name.

`sys.path` insertion here is idempotent/redundant with `conftest.py`'s own
(this directory's `conftest.py` inserts `_THIS_DIR` onto `sys.path` FIRST,
before any sibling `test_*.py` module — or this module itself — is
imported; this module repeats the same insertion so it also works if ever
imported standalone, e.g. from a REPL).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = _THIS_DIR.parents[2]

for _path in (REPO_ROOT, _THIS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

EVALS_DIR = REPO_ROOT / "evals"
FIXTURES_DIR = EVALS_DIR / "fixtures"
POLICY_TESTS_DIR = EVALS_DIR / "policy-tests"
REGRESSION_SUITES_DIR = EVALS_DIR / "regression-suites"

#: axis name -> the directory its fixtures live under. `forbidden_action`
#: lives under `policy-tests/` (README: "policy bundle 회귀 (deny/allow
#: 케이스)") rather than `fixtures/`, matching that directory's documented
#: scaffold purpose; every other axis lives under `fixtures/<axis>/`.
AXIS_FIXTURE_DIRS: dict[str, Path] = {
    "patch_correctness": FIXTURES_DIR / "patch_correctness",
    "contract_compliance": FIXTURES_DIR / "contract_compliance",
    "approval_enforcement": FIXTURES_DIR / "approval_enforcement",
    "tenant_isolation": FIXTURES_DIR / "tenant_isolation",
    "failure_recovery": FIXTURES_DIR / "failure_recovery",
    "reproducibility": FIXTURES_DIR / "reproducibility",
    "evidence_integrity": FIXTURES_DIR / "evidence_integrity",
    "forbidden_action": POLICY_TESTS_DIR / "forbidden_action",
    "handoff_completeness": FIXTURES_DIR / "handoff_completeness",
}

__all__ = [
    "AXIS_FIXTURE_DIRS",
    "EVALS_DIR",
    "FIXTURES_DIR",
    "POLICY_TESTS_DIR",
    "REGRESSION_SUITES_DIR",
    "REPO_ROOT",
]

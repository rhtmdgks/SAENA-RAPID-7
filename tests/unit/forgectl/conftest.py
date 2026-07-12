"""Shared fixtures for `saena_forgectl` unit tests.

`tests/` is not a package (no `tests/__init__.py`, mirroring the existing
`tests/unit/domain_identity`/`tests/unit/svc_engine_gateway` convention).
Two `sys.path` inserts happen here, both required because `tools/forgectl`
is deliberately not a `uv` workspace member (see
`tools/forgectl/README.md` "Packaging note" — workspace-membership edits
touch root `pyproject.toml`, outside this patch unit's exclusive write
paths):

1. this directory itself, so sibling test modules can `from conftest
   import ...` (the same pattern `tests/unit/domain_identity/conftest.py`
   documents).
2. `tools/forgectl/src`, so `import saena_forgectl` resolves at all —
   a normal workspace member gets this for free via `uv sync`'s editable
   install; this package does not participate in that, so the insert is
   done explicitly here instead.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_FORGECTL_SRC = _REPO_ROOT / "tools" / "forgectl" / "src"
_FIXTURES_DIR = _THIS_DIR / "fixtures"

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

if str(_FORGECTL_SRC) not in sys.path:
    sys.path.insert(0, str(_FORGECTL_SRC))


def fixture_path(name: str) -> Path:
    """Absolute path to a fixture file under `tests/unit/forgectl/fixtures/`."""
    return _FIXTURES_DIR / name


@pytest.fixture
def fixtures_dir() -> Path:
    return _FIXTURES_DIR


@pytest.fixture
def passing_values() -> dict[str, Any]:
    """The parsed `values-passing.yaml` fixture — a dict, ready to hand
    directly to a check function (bypassing file I/O) for tests that only
    care about check logic, not `load_values`."""
    import yaml

    with fixture_path("values-passing.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict)
    return data

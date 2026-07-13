"""pytest fixtures for `tests/unit/hooks_runtime`.

`tests/` is not a package (no `tests/__init__.py`, mirroring the existing
`tests/unit/forgectl`/`tests/unit/domain_persistence` convention). Two
`sys.path` inserts happen here, both required because
`packages/hooks-runtime` is deliberately not a `uv` workspace member (see
`packages/hooks-runtime/README.md` "Packaging note" — workspace-membership
edits touch root `pyproject.toml`, outside this patch unit's exclusive
write paths):

1. this directory itself, so sibling test modules can
   `from hooks_runtime_factories import ...` (see that module's own
   docstring for why factory helpers live there rather than under a bare
   `conftest` name).
2. `packages/hooks-runtime/src`, so `import saena_hooks_runtime` resolves
   at all — a normal workspace member gets this for free via `uv sync`'s
   editable install; this package does not participate in that, so the
   insert is done explicitly here instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_HOOKS_RUNTIME_SRC = _REPO_ROOT / "packages" / "hooks-runtime" / "src"
_CORPUS_DIR = _THIS_DIR / "corpus"

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

if str(_HOOKS_RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(_HOOKS_RUNTIME_SRC))

import pytest  # noqa: E402


def corpus_dir() -> Path:
    return _CORPUS_DIR


@pytest.fixture
def corpus_directory() -> Path:
    return _CORPUS_DIR

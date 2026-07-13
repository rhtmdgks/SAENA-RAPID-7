"""Shared fixtures for `tests/unit/vector_store` (w4-07).

`tests/` is not a package (no `tests/__init__.py`, mirroring the existing
`tests/unit/domain_identity`/`tests/unit/forgectl` convention). Two `sys.path`
inserts happen here, both required because `packages/vector-store` is
deliberately not (yet) a `uv` workspace member — see `packages/vector-store/
README.md` "Packaging note" (mirrors `tools/forgectl`'s own w2-19 -> w2-20
precedent):

1. this directory itself, so sibling test modules can `from
   vector_store_factories import ...` (the uniquely-named-module pattern
   `tests/unit/domain_persistence/persistence_factories.py`'s own docstring
   documents and requires — a bare `conftest` import collides across
   directories under pytest's default `prepend` import mode).
2. `packages/vector-store/src`, so `import saena_vector_store` resolves at
   all — a normal workspace member gets this for free via `uv sync`'s
   editable install; this package does not participate in that yet.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_VECTOR_STORE_SRC = _REPO_ROOT / "packages" / "vector-store" / "src"

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

if str(_VECTOR_STORE_SRC) not in sys.path:
    sys.path.insert(0, str(_VECTOR_STORE_SRC))

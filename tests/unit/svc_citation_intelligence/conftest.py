"""pytest fixtures for `tests/unit/svc_citation_intelligence` (w4-05).

Two `sys.path` inserts, mirroring the existing `tests/unit/svc_observer_
discovery`/`tests/unit/vector_store` convention exactly: `services/
intelligence/citation-intelligence-service` is deliberately NOT a `uv`
workspace member yet (see that package's `pyproject.toml` NOTE —
registering a new workspace member touches root `pyproject.toml`, outside
this unit's exclusive write paths). A normal workspace member gets its
`src/` on `sys.path` for free via `uv sync`'s editable install; this
package does not participate in that yet, so the insert below does it
explicitly instead. The first insert (this directory itself) lets sibling
test modules `from citation_intelligence_factories import ...` (the
uniquely-named-module pattern `tests/unit/domain_persistence/
persistence_factories.py`'s own docstring documents and requires — a bare
`conftest` import collides across directories under pytest's default
`prepend` import mode).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_CITATION_INTELLIGENCE_SRC = (
    _REPO_ROOT / "services" / "intelligence" / "citation-intelligence-service" / "src"
)

for _path in (_THIS_DIR, _CITATION_INTELLIGENCE_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

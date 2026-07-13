"""pytest fixtures for `tests/unit/svc_entity_resolution`.

`services/intelligence/entity-resolution-service` is deliberately NOT a `uv`
workspace member yet (see that package's `pyproject.toml` "NOTE" —
registering a new workspace member touches root `pyproject.toml`, outside
this unit's exclusive write paths; same precedent as
`tests/unit/svc_observer_discovery/conftest.py` and `tests/unit/
vector_store/conftest.py`). A normal workspace member gets its `src/` on
`sys.path` for free via `uv sync`'s editable install; this package does not
participate in that yet, so the insert below does it explicitly instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_ENTITY_RESOLUTION_SRC = (
    _REPO_ROOT / "services" / "intelligence" / "entity-resolution-service" / "src"
)

for _path in (_THIS_DIR, _ENTITY_RESOLUTION_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

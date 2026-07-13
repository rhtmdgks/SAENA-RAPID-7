"""pytest fixtures for `tests/unit/svc_observer_discovery`.

Three `sys.path` inserts happen here — the first mirrors the existing
`tests/unit/svc_artifact_registry`/`tests/unit/domain_persistence`
convention (sibling test modules can `from observer_discovery_factories
import ...`); the other two are required because BOTH
`services/acquisition/site-discovery-service` and
`services/acquisition/chatgpt-observer-service` are deliberately NOT `uv`
workspace members yet (see either service's `pyproject.toml` "NOTE" —
registering a new workspace member touches root `pyproject.toml`, outside
this unit's exclusive write paths; same precedent as
`tests/unit/hooks_runtime/conftest.py`, added by
unit/w3-06-hooks-runtime, for `packages/hooks-runtime`). A normal workspace
member gets its `src/` on `sys.path` for free via `uv sync`'s editable
install; these two packages do not participate in that, so the inserts
below do it explicitly instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_SITE_DISCOVERY_SRC = _REPO_ROOT / "services" / "acquisition" / "site-discovery-service" / "src"
_CHATGPT_OBSERVER_SRC = _REPO_ROOT / "services" / "acquisition" / "chatgpt-observer-service" / "src"

for _path in (_THIS_DIR, _SITE_DISCOVERY_SRC, _CHATGPT_OBSERVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

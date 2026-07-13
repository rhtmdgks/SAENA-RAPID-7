"""pytest fixtures for `tests/unit/svc_claim_evidence`.

Two `sys.path` inserts happen here — the first mirrors the existing
`tests/unit/svc_observer_discovery`/`tests/unit/svc_artifact_registry`
convention (sibling test modules can `from claim_evidence_factories import
...`); the second is required because
`services/intelligence/claim-evidence-service` is deliberately NOT a `uv`
workspace member yet (see its `pyproject.toml` NOTE — registering a new
workspace member touches root `pyproject.toml`, outside this unit's
exclusive write paths; same precedent as
`tests/unit/svc_observer_discovery/conftest.py`, w3-05). A normal
workspace member gets its `src/` on `sys.path` for free via `uv sync`'s
editable install; this package does not participate in that yet, so the
insert below does it explicitly instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_CLAIM_EVIDENCE_SRC = _REPO_ROOT / "services" / "intelligence" / "claim-evidence-service" / "src"

for _path in (_THIS_DIR, _CLAIM_EVIDENCE_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

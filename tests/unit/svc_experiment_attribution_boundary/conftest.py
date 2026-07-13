"""pytest fixtures/sys.path wiring for `tests/unit/svc_experiment_attribution_boundary`.

Two `sys.path` inserts, mirroring the existing `tests/unit/svc_claim_evidence`/
`tests/unit/svc_observer_discovery` convention: `services/experimentation/
experiment-attribution-service` is deliberately NOT a `uv` workspace member
yet (registering a new workspace member touches root `pyproject.toml`, which
is w5-10's exclusive path here, not w5-12's — same precedent as
`tests/unit/svc_claim_evidence/conftest.py`, w4-05). A normal workspace
member gets its `src/` on `sys.path` for free via `uv sync`'s editable
install; this package does not participate in that yet, so the insert below
does it explicitly instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_EXPERIMENT_ATTRIBUTION_SRC = (
    _REPO_ROOT / "services" / "experimentation" / "experiment-attribution-service" / "src"
)

for _path in (_THIS_DIR, _EXPERIMENT_ATTRIBUTION_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

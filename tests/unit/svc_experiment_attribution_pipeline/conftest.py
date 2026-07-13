"""pytest fixtures for `tests/unit/svc_experiment_attribution_pipeline`.

`services/experimentation/experiment-attribution-service` is deliberately NOT
a `uv` workspace member yet (mirrors the documented
`services/acquisition/site-discovery-service` / `chatgpt-observer-service`
precedent — see either service's `pyproject.toml` NOTE and
`tests/unit/svc_observer_discovery/conftest.py`, the exact pattern this
conftest follows). Registering a new workspace member touches root
`pyproject.toml`, which is Integrator-exclusive per wave5-plan.md's DAG. A
normal workspace member gets its `src/` on `sys.path` for free via `uv
sync`'s editable install; this package does not participate in that, so the
insert below does it explicitly instead.
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

"""pytest fixtures for `tests/unit/svc_experiment_attribution_persistence` (w5-10).

Two `sys.path` inserts — the first lets sibling test modules import shared
helpers by bare name (mirrors `tests/unit/svc_claim_evidence` etc.); the second
is required because `services/experimentation/experiment-attribution-service`
is deliberately NOT a `uv` workspace member yet (see its `pyproject.toml`
NOTE — registering a new workspace member touches root `pyproject.toml`,
outside this unit's exclusive write paths; same precedent as
`tests/unit/svc_claim_evidence/conftest.py`, w4-04). A normal workspace member
gets its `src/` on `sys.path` for free via `uv sync`'s editable install; this
package does not participate in that yet, so the insert below does it
explicitly instead.

These unit tests import ONLY the PURE persistence sub-modules (`tables`,
`fingerprint`, `mapping`) — never `adapter` (the real-driver module needs a
live database and is covered by the integration lane), so no engine/testcontainer
machinery is needed here.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_SERVICE_SRC = (
    _REPO_ROOT / "services" / "experimentation" / "experiment-attribution-service" / "src"
)

for _path in (_THIS_DIR, _SERVICE_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

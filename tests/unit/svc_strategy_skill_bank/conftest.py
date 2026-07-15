"""pytest fixtures for `tests/unit/svc_strategy_skill_bank`.

Two `sys.path` inserts happen here — the first mirrors the existing
`tests/unit/svc_claim_evidence`/`tests/unit/svc_observer_discovery`
convention (sibling test modules can `from skill_bank_factories import
...`); the second is required because
`services/experimentation/strategy-skill-bank-service` is deliberately NOT a
`uv` workspace member yet (see its `pyproject.toml` NOTE — registering a new
workspace member touches root `pyproject.toml`, outside this unit's
exclusive write paths; same precedent as
`tests/unit/svc_claim_evidence/conftest.py`, w4-04). A normal workspace
member gets its `src/` on `sys.path` for free via `uv sync`'s editable
install; this package does not participate in that yet, so the insert below
does it explicitly instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_STRATEGY_SKILL_BANK_SRC = (
    _REPO_ROOT / "services" / "experimentation" / "strategy-skill-bank-service" / "src"
)

for _path in (_THIS_DIR, _STRATEGY_SKILL_BANK_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

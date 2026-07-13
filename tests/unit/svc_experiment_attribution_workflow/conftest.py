"""pytest setup for ``tests/unit/svc_experiment_attribution_workflow``.

``experiment-attribution-service`` is not (yet) a uv workspace member — its
``pyproject.toml`` is another unit's exclusive path (w5-10/w5-12) and w5-14 must
NOT create it or touch root config. So ``saena_experiment_attribution`` is not
pip-installed; this conftest inserts BOTH the service ``src`` directory and this
test directory onto ``sys.path`` (same discipline as
``tests/unit/svc_orchestrator/conftest.py``) so the workflow package imports and
test modules can ``from attribution_factories import ...`` /
``from conftest import ...``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[2]
_SVC_SRC = _REPO_ROOT / "services" / "experimentation" / "experiment-attribution-service" / "src"

for _path in (_SVC_SRC, _THIS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


import pytest  # noqa: E402 (after sys.path setup)
from attribution_factories import make_accepted  # noqa: E402


@pytest.fixture
def accepted():  # noqa: ANN201 - fixture return type is the domain Accepted
    return make_accepted()

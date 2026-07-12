"""pytest fixtures for `tests/unit/svc_orchestrator`.

Mirrors the `tests/unit/svc_policy_gate` convention: this directory is
inserted onto `sys.path` so test modules can
`from orchestrator_factories import ...`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

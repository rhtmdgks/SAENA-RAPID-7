"""pytest fixtures for `tests/unit/domain_qeeg`.

Same `sys.path` insertion pattern as `tests/unit/domain_bus/conftest.py` —
this directory is inserted onto `sys.path` so sibling test modules can
`from qeeg_factories import ...` under a uniquely-named module (see that
module's own docstring for the import-collision rationale).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

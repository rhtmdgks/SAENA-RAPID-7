"""pytest path shim for `tests/unit/domain_measurement_ports` (w5-09).

`tests/` is not a package (no `tests/__init__.py`, matching the existing
`tests/unit/domain_persistence` convention). This directory is inserted onto
`sys.path` so sibling test modules can `from measurement_factories import ...`
under that unique dotted name (never a second `conftest`, which would collide
with another directory's `conftest` in a full-suite run — see
`tests/unit/domain_persistence/persistence_factories.py`'s docstring for the
empirically-observed collision this avoids).
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

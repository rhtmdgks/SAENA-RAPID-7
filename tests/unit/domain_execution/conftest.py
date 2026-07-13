"""pytest fixtures/setup for `tests/unit/domain_execution`.

Inserts this directory onto `sys.path` (mirroring the
`tests/unit/domain_persistence` convention exactly) so sibling test modules
can `from _schema_support import ...` — the package `__init__.py` this
directory now carries disambiguates this directory's `test_*.py` module
NAMES from same-named modules in sibling test directories (e.g.
`test_errors.py` also exists under `tests/unit/domain_identity`), but does
NOT by itself put this directory on `sys.path` for bare sibling imports —
that is what this explicit insertion is for.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

"""pytest configuration for tests/contract/validate.

Mirrors tests/contract/conftest.py's rationale: this directory has no
`__init__.py` (not a package, tests/contract/README.md layout), so
sibling modules importing the local `_support` helper module need this
directory on `sys.path` explicitly rather than relying on
package-relative imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

_VALIDATE_DIR = Path(__file__).resolve().parent

if str(_VALIDATE_DIR) not in sys.path:
    sys.path.insert(0, str(_VALIDATE_DIR))

"""sys.path wiring for the skill-bundle enforcement tests (w6-08).

`tests/` is not a package (repo convention — see
`tests/unit/skills_manifest/conftest.py`). Two `sys.path` inserts:

1. this directory, so test modules can `from bundle_fixtures import ...`
   (deliberately NOT named `conftest` — `tests/unit/skills_manifest` already
   binds the plain module name `conftest` when both directories run in one
   pytest session, so this tree uses a unique helper-module name);
2. `tools/validation`, so `import skill_bundle` / `import skill_manifest`
   resolve (single-file validators, not workspace members).

All fixtures/helpers live in `bundle_fixtures.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_VALIDATION_DIR = _REPO_ROOT / "tools" / "validation"

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
if str(_VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(_VALIDATION_DIR))

from bundle_fixtures import manifest_data  # noqa: E402,F401  (fixture registration)

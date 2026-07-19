"""Path setup + fixture re-export for the skill-manifest validator tests.

Unique-basename convention: shared helpers/fixtures live in
`_manifest_fixtures.py` (NOT `conftest`) and test modules are prefixed
`test_skill_manifest_*` — plain basenames like `test_cli.py` /
`from conftest import ...` collide across this repo's non-package test
leaf dirs in a combined session (rootdir-wide module cache; same footgun
w6-08/w6-11 hit). The star-import below re-exports the pytest fixtures
into conftest's namespace so pytest auto-discovers them.
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

from _manifest_fixtures import *  # noqa: E402,F401,F403
from _manifest_fixtures import manifest_data  # noqa: E402,F401  (fixture; not in __all__)

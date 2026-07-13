"""pytest fixtures/sys.path wiring for `tests/e2e/intelligence` (w4-17).

`tests/` is not a package — `intelligence_e2e_harness.py` needs to be
`import`-able BY NAME from this directory's own test modules AND from
`tests/integration/intelligence_e2e/**` (the ClickHouse-backed companion
lane reuses this SAME harness so both lanes build from byte-identical
synthetic input — see that harness module's own docstring). Every
`saena_*` package this suite exercises is already a registered `uv`
workspace member (no `src`-path insertion needed for those); only this
directory itself needs to be on `sys.path` so `from intelligence_e2e_harness
import ...` resolves.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

"""pytest configuration for tests/contract.

`tests/` is not a package (no `tests/__init__.py`, no `tests/contract/__init__.py`
by design — see tests/contract/README.md layout). `tests/contract/harness` is a
plain directory tree used as an internal import target (`import harness`,
`from harness import registry, tags, diff, rules, util`) by modules under
`tests/contract/compat/` and `tests/contract/` itself.

pytest's rootdir-relative sys.path insertion (rootdir-conftest-first-import)
does not guarantee `tests/contract` is importable as `harness`'s parent unless
we insert it explicitly — so this conftest prepends the directory containing
this file (`tests/contract/`) to `sys.path` once, before any test module in
this tree is collected. This mirrors the existing project convention of
explicit-path pytest invocation (`uv run pytest tests/contract`, per
tests/contract/README.md Constraints) rather than package-relative imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

_CONTRACT_TESTS_DIR = Path(__file__).resolve().parent

if str(_CONTRACT_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTRACT_TESTS_DIR))

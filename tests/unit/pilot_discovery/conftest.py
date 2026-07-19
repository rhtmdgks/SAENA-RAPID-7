"""Shared fixtures for w6-12 discovery/docker-preflight tests.

`tests/` is not a package (repo convention). Two sys.path inserts: this
directory (so tests can `from _discovery_fixtures import …` — a unique module
name, never shared with `tests/unit/pilot`) and the pilot src tree (no-op
once `uv sync`'s editable install provides `saena_pilot`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_PILOT_SRC = _REPO_ROOT / "tools" / "saena-pilot" / "src"

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
if str(_PILOT_SRC) not in sys.path:
    sys.path.insert(0, str(_PILOT_SRC))

from _discovery_fixtures import make_rapid7_fixture  # noqa: E402


@pytest.fixture
def pilot_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "pilot-home"
    monkeypatch.setenv("SAENA_PILOT_HOME", str(home))
    return home


@pytest.fixture
def rapid7_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = make_rapid7_fixture(tmp_path / "rapid7")
    monkeypatch.chdir(root)
    return root

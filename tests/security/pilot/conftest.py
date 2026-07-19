"""Fixtures for the `saena_pilot` adversarial security suite (w6-13).

`tests/` is not a package (repo convention). Two `sys.path` inserts: this
directory (so test modules can `from _sec_fixtures import …` — a unique name,
NOT `conftest`, to dodge the cross-directory `conftest` module-cache collision
in full-suite runs) and `tools/saena-pilot/src` (an idempotent no-op once the
editable install from `uv sync` already provides `saena_pilot`).

Every fixture builds in `tmp_path` with real `git init` subprocesses. There
is NO network use and NO real `claude`/`docker` process — the `stub_bin`
fixture puts recording stubs on PATH so a launch, if it ever happened, is
observable without executing anything real.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[2]
_PILOT_SRC = _REPO_ROOT / "tools" / "saena-pilot" / "src"

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
if str(_PILOT_SRC) not in sys.path:
    sys.path.insert(0, str(_PILOT_SRC))

from _sec_fixtures import make_git_repo, make_rapid7_fixture  # noqa: E402


@pytest.fixture
def pilot_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """SAENA_PILOT_HOME pointed at an isolated tmp dir (outside both repos)."""
    home = tmp_path / "pilot-home"
    monkeypatch.setenv("SAENA_PILOT_HOME", str(home))
    return home


@pytest.fixture
def rapid7_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fixture RAPID-7 checkout; cwd is chdir'd here (as `entry()` requires)."""
    root = make_rapid7_fixture(tmp_path / "rapid7")
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def customer_repo(tmp_path: Path) -> Path:
    # Spaces + Unicode (한글) in the path are part of the boundary contract.
    return make_git_repo(tmp_path / "customer 저장소 α")


@pytest.fixture
def complete_intake(tmp_path: Path) -> Path:
    """An intake file that completes the action contract (for implement mode)."""
    intake = {
        "customer_id": "tenant-042",
        "allowed_write_scope": ["src/**", "docs/**"],
        "protected_paths": [".github/**", "deploy/**"],
        "build_commands": ["npm run build"],
        "test_commands": "auto-detect-pending",
        "deployment_responsibility": "human",
        "data_classification": "confidential",
        "observation_authorization": {"authorized": True, "owner": "Jane Doe"},
    }
    path = tmp_path / "intake.json"
    path.write_text(json.dumps(intake, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def stub_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Recording stubs for `claude` AND `docker` on PATH.

    Each records its argv to a per-tool marker file and exits 0, so a launch
    can be observed (and proven NOT to be a deploy) without executing anything
    real. Returns the directory holding the marker files.
    """
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    markers = tmp_path / "invocations"
    markers.mkdir()
    for tool in ("claude", "docker"):
        marker = markers / f"{tool}.txt"
        script = bin_dir / tool
        script.write_text(
            f'#!/bin/sh\nprintf \'%s\\n\' "$@" >> "{marker}"\nexit 0\n',
            encoding="utf-8",
        )
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return markers

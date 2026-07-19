"""Shared fixtures for `saena_pilot` unit tests.

`tests/` is not a package (repo convention — see `tests/unit/forgectl/
conftest.py`). Two `sys.path` inserts: this directory (so sibling test
modules can `from _pilot_fixtures import …` — a unique name, NOT `conftest`,
to avoid the cross-directory `conftest` module-cache collision in full-suite
runs) and `tools/saena-pilot/src` (idempotent no-op once the editable install
from `uv sync` already provides `saena_pilot`).

Fixture strategy: everything is built in `tmp_path` via real `git init`
subprocesses — no network, no real `claude` launch (launcher is exercised via
`--dry-run`, an injectable runner, and a PATH stub). The fixture RAPID-7 root
carries a small but VALID skill bundle (fixture manifest + fixture validator
script); the real 16-skill bundle lands in parallel units w6-01..07.
"""

from __future__ import annotations

import json
import os
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

from _pilot_fixtures import make_git_repo, make_rapid7_fixture  # noqa: E402


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


@pytest.fixture
def customer_repo(tmp_path: Path) -> Path:
    # Spaces + Unicode (한글) in the path are part of the contract.
    return make_git_repo(tmp_path / "customer 저장소 α")


@pytest.fixture
def complete_intake(tmp_path: Path) -> Path:
    """An intake file that completes the action contract."""
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
def stub_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stub `claude` on PATH that records every invocation to a marker
    file — proves --dry-run does NOT execute, and lets non-dry-run launches
    be observed without a real Claude Code session."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    marker = tmp_path / "claude-invocations.txt"
    script = bin_dir / "claude"
    script.write_text(
        f'#!/bin/sh\nprintf \'%s\\n\' "$@" >> "{marker}"\nexit 0\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return marker

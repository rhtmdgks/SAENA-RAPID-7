"""Shared fixtures for the skill-pack sync/drift-gate tests (w6-09).

`tests/` is not a package (repo convention — see
`tests/unit/forgectl/conftest.py`). Two `sys.path` inserts:

1. this directory, so sibling test modules can `from conftest import ...`;
2. `tools/validation`, so `import skill_pack_sync` (and its sibling
   delegate `skill_manifest`) resolve — single-file validators, deliberately
   not workspace members.

The REAL checked-in tree (canonical `.claude/skills/**`, generated
`plugins/saena-skill-pack/**`, root `.claude-plugin/marketplace.json`) is
regression-tested read-only; every MUTATION test first copies that tree
into `tmp_path` (the `pack_repo` fixture) so the working tree is never
modified.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_VALIDATION_DIR = _REPO_ROOT / "tools" / "validation"

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
if str(_VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(_VALIDATION_DIR))

import skill_pack_sync  # noqa: E402

REPO_ROOT = _REPO_ROOT
CANONICAL_SKILLS = REPO_ROOT / ".claude" / "skills"
PLUGIN_DIR = REPO_ROOT / "plugins" / "saena-skill-pack"
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"

__all__ = [
    "CANONICAL_SKILLS",
    "MARKETPLACE_JSON",
    "PLUGIN_DIR",
    "REPO_ROOT",
    "load_json",
    "run_cli",
    "skill_pack_sync",
    "write_json",
]


@pytest.fixture
def pack_repo(tmp_path: Path) -> Path:
    """Copy of every skill-pack-relevant tree of the REAL repo, safe to mutate."""
    root = tmp_path / "repo"
    shutil.copytree(CANONICAL_SKILLS, root / ".claude" / "skills")
    shutil.copytree(PLUGIN_DIR, root / "plugins" / "saena-skill-pack")
    (root / ".claude-plugin").mkdir(parents=True)
    shutil.copy2(MARKETPLACE_JSON, root / ".claude-plugin" / "marketplace.json")
    return root


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_cli(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str]:
    """Invoke `skill_pack_sync.main` and return (exit_code, stdout)."""
    code = skill_pack_sync.main(argv)
    return code, capsys.readouterr().out

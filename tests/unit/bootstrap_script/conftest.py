"""Fixtures for the ``scripts/bootstrap-claude.sh`` unit tests (w6-10).

Pure-subprocess suite — no ``sys.path`` inserts are needed here (the
``tests/unit/forgectl``-style conftest pattern is unnecessary; nothing is
imported from a package under test).

Every invocation runs with an isolated ``HOME`` + ``CLAUDE_CONFIG_DIR`` and
a restricted ``PATH`` (stub-shim dir + ``/usr/bin:/bin``) so tool
visibility is deterministic on macOS and CI (ubuntu) alike: ``uv`` /
``claude`` resolve to the committed stubs in
``tools/validation/bootstrap-tests/shims/`` and ``git``/``awk``/... come
from the OS. The stubs fail loudly (exit 97) on any invocation form the
bootstrap script is not allowed to run (deny-unpinned-install allowlist).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "bootstrap-claude.sh"
BOOTSTRAP_TESTS_DIR = REPO_ROOT / "tools" / "validation" / "bootstrap-tests"
SHIMS_DIR = BOOTSTRAP_TESTS_DIR / "shims"
BASE_PATH = "/usr/bin:/bin"

HOOK_SCRIPT_NAMES = (
    "deny-deploy-push",
    "deny-unpinned-install",
    "protect-paths",
    "audit-log",
    "secret-scan",
)

RunResult = subprocess.CompletedProcess[str]
EnvBuilder = Callable[..., dict[str, str]]
Runner = Callable[..., RunResult]
RepoFactory = Callable[..., Path]


@pytest.fixture
def bootstrap_env(tmp_path: Path) -> EnvBuilder:
    """Build a deterministic child environment for one script invocation."""

    def _env(shims: str = "ok", extra_env: Mapping[str, str] | None = None) -> dict[str, str]:
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        config_dir = tmp_path / "claude-config"
        config_dir.mkdir(exist_ok=True)
        env = {
            "PATH": f"{SHIMS_DIR / shims}:{BASE_PATH}",
            "HOME": str(home),
            "CLAUDE_CONFIG_DIR": str(config_dir),
        }
        if extra_env:
            env.update(extra_env)
        return env

    return _env


@pytest.fixture
def run_bootstrap(bootstrap_env: EnvBuilder) -> Runner:
    """Run bootstrap-claude.sh via ``sh`` with an isolated environment."""

    def _run(
        args: Iterable[str],
        *,
        shims: str = "ok",
        script: Path = SCRIPT,
        cwd: Path | str | None = None,
        extra_env: Mapping[str, str] | None = None,
    ) -> RunResult:
        return subprocess.run(
            ["sh", str(script), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd is not None else str(REPO_ROOT),
            env=bootstrap_env(shims=shims, extra_env=extra_env),
            check=False,
        )

    return _run


@pytest.fixture
def fixture_repo_factory() -> RepoFactory:
    """Create a minimal SAENA-RAPID-7 repo skeleton the script can verify.

    Deliberately NOT a git repository, so the marker walk-up fallback of the
    repo-root autodiscovery is exercised (git rev-parse fails there).
    """

    def _make(
        dest: Path,
        *,
        agent_count: int = 14,
        hook_names: Iterable[str] = HOOK_SCRIPT_NAMES,
        kill_switch: bool = False,
        with_plugin: bool = False,
        with_skills_manifest: bool = False,
    ) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / ".tool-versions", dest / ".tool-versions")

        claude_dir = dest / ".claude"
        (claude_dir / "hooks" / "scripts").mkdir(parents=True)
        (claude_dir / "settings.json").write_text("{}\n", encoding="utf-8")
        for name in hook_names:
            hook = claude_dir / "hooks" / "scripts" / f"{name}.sh"
            hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        if kill_switch:
            (claude_dir / "hooks" / "DISABLED").write_text("", encoding="utf-8")

        agents_dir = claude_dir / "agents"
        agents_dir.mkdir()
        (agents_dir / "README.md").write_text("# stub agents\n", encoding="utf-8")
        for i in range(agent_count):
            (agents_dir / f"agent-{i:02d}.md").write_text("# stub agent\n", encoding="utf-8")

        (claude_dir / "skills").mkdir()
        if with_skills_manifest:
            manifest = claude_dir / "skills" / "manifest.json"
            manifest.write_text('{"schema_version": "saena.skill-manifest/v1"}\n', encoding="utf-8")

        worktree_tool = dest / "tools" / "development" / "worktree.sh"
        worktree_tool.parent.mkdir(parents=True)
        worktree_tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

        (dest / "pyproject.toml").write_text(
            '[project]\nname = "fixture"\nversion = "0"\n', encoding="utf-8"
        )
        (dest / "uv.lock").write_text("", encoding="utf-8")
        (dest / ".venv").mkdir()

        scripts_dir = dest / "scripts"
        scripts_dir.mkdir()
        shutil.copy(SCRIPT, scripts_dir / "bootstrap-claude.sh")

        if with_plugin:
            plugin_meta = dest / ".claude-plugin"
            plugin_meta.mkdir()
            marketplace = {
                "name": "saena-rapid-7",
                "owner": {"name": "SAENA"},
                "plugins": [{"name": "saena-skill-pack", "source": "./plugins/saena-skill-pack"}],
            }
            (plugin_meta / "marketplace.json").write_text(
                json.dumps(marketplace) + "\n", encoding="utf-8"
            )
            (dest / "plugins" / "saena-skill-pack").mkdir(parents=True)

        return dest

    return _make


def snapshot_tree(root: Path) -> dict[str, str]:
    """Map every file under ``root`` (relative path) to its content hash."""
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_dir():
            snapshot[rel] = "<dir>"
        elif path.is_file():
            snapshot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


@pytest.fixture
def tree_snapshot() -> Callable[[Path], dict[str, str]]:
    return snapshot_tree

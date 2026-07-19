"""Sourcing-safety, shellcheck, and corpus-runner tests for w6-10.

The bootstrap script must never terminate a parent interactive shell when
sourced — it finishes via ``return``, so ``echo ALIVE`` after the dot-source
must always run, in bash and (when available on the host) zsh, even when a
required tool is missing.

Linux verification of all of this happens in CI (ubuntu); locally these
tests exercise the host shells only.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

# tests/ is not a package: importing sibling conftest by name would be
# collision-prone across leaf test dirs, so fixture types are aliased here.
EnvBuilder = Callable[..., dict[str, str]]

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "bootstrap-claude.sh"
RUN_CORPUS = REPO_ROOT / "tools" / "validation" / "bootstrap-tests" / "run-corpus.sh"

SOURCE_PROBE = '. "$1" --check >/dev/null 2>&1; echo "ALIVE:$?"'


def _source_in(
    shell: str, env: dict[str, str], script: Path = SCRIPT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shell, "-c", SOURCE_PROBE, shell, str(script)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        check=False,
    )


def test_sourcing_in_bash_never_kills_parent(bootstrap_env: EnvBuilder) -> None:
    result = _source_in("bash", bootstrap_env(shims="ok"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ALIVE:0"


def test_sourcing_in_bash_with_missing_tool_never_kills_parent(bootstrap_env: EnvBuilder) -> None:
    result = _source_in("bash", bootstrap_env(shims="no-uv"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ALIVE:1"  # failure is reported, parent survives


def test_sourcing_in_zsh_never_kills_parent(bootstrap_env: EnvBuilder) -> None:
    if shutil.which("zsh") is None:
        pytest.skip("zsh not available on this host (CI ubuntu ships no zsh by default)")
    result = _source_in("zsh", bootstrap_env(shims="ok"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ALIVE:0"


def test_shellcheck_clean() -> None:
    if shutil.which("shellcheck") is not None:
        cmd = ["shellcheck", str(SCRIPT), str(RUN_CORPUS)]
    elif shutil.which("uv") is not None:
        # hook-allowlisted ephemeral form; pinned (uvx --from pkg==ver)
        cmd = [
            "uvx",
            "--from",
            "shellcheck-py==0.10.0.1",
            "shellcheck",
            str(SCRIPT),
            str(RUN_CORPUS),
        ]
    else:
        pytest.skip("neither shellcheck nor uv is available to run shellcheck")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_corpus_runner_green() -> None:
    result = subprocess.run(
        ["sh", str(RUN_CORPUS)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Fail: 0" in result.stdout

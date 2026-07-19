"""Fixture-repo tests for scripts/bootstrap-claude.sh (w6-10).

These copy a minimal repo skeleton into pytest tmp dirs (including a
"dir with spaces/한글 리포" path) so degraded states — kill-switch present,
hook script missing, plugin packaging present/absent — can be exercised
without ever mutating the real checkout. The skeletons are deliberately not
git repositories, which also exercises the marker-walk-up root fallback.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

# tests/ is not a package: importing sibling conftest by name would be
# collision-prone across leaf test dirs, so fixture types are aliased here.
Runner = Callable[..., subprocess.CompletedProcess[str]]
RepoFactory = Callable[..., Path]
TreeSnapshot = Callable[[Path], dict[str, str]]


def _check(stdout: str, check_id: str) -> dict[str, str]:
    report: dict[str, Any] = json.loads(stdout)
    matches = [c for c in report["checks"] if c["id"] == check_id]
    assert len(matches) == 1
    return matches[0]


def test_repo_with_spaces_and_unicode_path(
    tmp_path: Path, fixture_repo_factory: RepoFactory, run_bootstrap: Runner
) -> None:
    repo = fixture_repo_factory(tmp_path / "dir with spaces" / "한글 리포")
    script = repo / "scripts" / "bootstrap-claude.sh"
    result = run_bootstrap(["--check", "--json"], script=script, cwd="/")
    assert result.returncode == 0, result.stdout + result.stderr
    root_check = _check(result.stdout, "repo-root")
    assert root_check["status"] == "PASS"
    assert "한글 리포" in root_check["detail"]
    assert "dir with spaces" in root_check["detail"]


def test_kill_switch_present_is_red_warn_not_pass(
    tmp_path: Path, fixture_repo_factory: RepoFactory, run_bootstrap: Runner
) -> None:
    repo = fixture_repo_factory(tmp_path / "repo", kill_switch=True)
    script = repo / "scripts" / "bootstrap-claude.sh"
    result = run_bootstrap(["--check", "--json"], script=script)
    assert result.returncode == 0  # WARN does not fail the run...
    kill_check = _check(result.stdout, "hook-kill-switch")
    assert kill_check["status"] == "WARN"  # ...but it must never be PASS
    assert "DISABLED" in kill_check["detail"]
    assert "remove" in kill_check["remedy"]


def test_missing_hook_script_fails(
    tmp_path: Path, fixture_repo_factory: RepoFactory, run_bootstrap: Runner
) -> None:
    hooks = ("deny-deploy-push", "deny-unpinned-install", "protect-paths", "audit-log")
    repo = fixture_repo_factory(tmp_path / "repo", hook_names=hooks)  # secret-scan missing
    script = repo / "scripts" / "bootstrap-claude.sh"
    result = run_bootstrap(["--check", "--json"], script=script)
    assert result.returncode == 1
    hook_check = _check(result.stdout, "hook-scripts")
    assert hook_check["status"] == "FAIL"
    assert "secret-scan" in hook_check["detail"]


def test_skills_manifest_absent_is_na_and_present_is_pass(
    tmp_path: Path, fixture_repo_factory: RepoFactory, run_bootstrap: Runner
) -> None:
    without = fixture_repo_factory(tmp_path / "without")
    result = run_bootstrap(
        ["--check", "--json"], script=without / "scripts" / "bootstrap-claude.sh"
    )
    assert _check(result.stdout, "skills-manifest")["status"] == "N/A"

    with_manifest = fixture_repo_factory(tmp_path / "with", with_skills_manifest=True)
    result = run_bootstrap(
        ["--check", "--json"], script=with_manifest / "scripts" / "bootstrap-claude.sh"
    )
    assert _check(result.stdout, "skills-manifest")["status"] == "PASS"


def test_plugin_packaging_absent_reports_na_honestly(
    tmp_path: Path, fixture_repo_factory: RepoFactory, run_bootstrap: Runner
) -> None:
    repo = fixture_repo_factory(tmp_path / "repo", with_plugin=False)
    result = run_bootstrap(["--check", "--json"], script=repo / "scripts" / "bootstrap-claude.sh")
    plugin_check = _check(result.stdout, "plugin-bundle")
    assert plugin_check["status"] == "N/A"  # honest: neither PASS nor FAIL
    assert "not present" in plugin_check["detail"]


def test_plugin_packaging_present_check_and_install(
    tmp_path: Path, fixture_repo_factory: RepoFactory, run_bootstrap: Runner
) -> None:
    repo = fixture_repo_factory(tmp_path / "repo", with_plugin=True)
    script = repo / "scripts" / "bootstrap-claude.sh"
    check = run_bootstrap(["--check", "--json"], script=script)
    assert _check(check.stdout, "plugin-bundle")["status"] == "PASS"  # stub marketplace lists it
    install = run_bootstrap(["--install", "--json"], script=script)
    plugin_check = _check(install.stdout, "plugin-bundle")
    assert plugin_check["status"] == "PASS"
    assert "saena-skill-pack" in plugin_check["detail"]


def test_second_install_run_is_identical_noop(
    tmp_path: Path, fixture_repo_factory: RepoFactory, run_bootstrap: Runner
) -> None:
    repo = fixture_repo_factory(tmp_path / "repo")
    script = repo / "scripts" / "bootstrap-claude.sh"
    first = run_bootstrap(["--install", "--json"], script=script)
    second = run_bootstrap(["--install", "--json"], script=script)
    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0
    assert first.stdout == second.stdout  # identical machine-readable report
    assert json.loads(first.stdout)["mode"] == "install"
    human_one = run_bootstrap(["--install"], script=script)
    human_two = run_bootstrap(["--install"], script=script)
    assert human_one.stdout == human_two.stdout


def test_install_only_runs_hook_allowlisted_uv_forms(
    tmp_path: Path, fixture_repo_factory: RepoFactory, run_bootstrap: Runner
) -> None:
    repo = fixture_repo_factory(tmp_path / "repo")
    script = repo / "scripts" / "bootstrap-claude.sh"
    log = tmp_path / "uv-invocations.log"
    result = run_bootstrap(
        ["--install", "--json"], script=script, extra_env={"UV_STUB_LOG": str(log)}
    )
    assert result.returncode == 0
    invocations = [line for line in log.read_text().splitlines() if line]
    assert invocations, "expected the install to consult uv"
    allowed_prefixes = (
        "--version",
        "python find ",
        "sync --locked",
        "lock",
        "tool dir --bin",
        "tool install rust-just==",
        "tool install shellcheck-py==",
    )
    for invocation in invocations:
        assert invocation.startswith(allowed_prefixes), (
            f"non-allowlisted uv invocation: {invocation!r}"
        )


def test_check_mode_mutates_nothing(
    tmp_path: Path,
    fixture_repo_factory: RepoFactory,
    run_bootstrap: Runner,
    tree_snapshot: TreeSnapshot,
) -> None:
    repo = fixture_repo_factory(tmp_path / "repo")
    script = repo / "scripts" / "bootstrap-claude.sh"
    home = tmp_path / "home"  # created by the runner fixture
    before_repo = tree_snapshot(repo)
    result = run_bootstrap(["--check", "--json"], script=script)
    assert result.returncode == 0
    assert tree_snapshot(repo) == before_repo
    assert tree_snapshot(home) == {}  # read-only mode wrote nothing to HOME

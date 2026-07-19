"""CLI-contract tests for scripts/bootstrap-claude.sh (w6-10).

Run against the real repository checkout with deterministic stub shims
(``uv``/``claude``) and isolated HOME/CLAUDE_CONFIG_DIR. See conftest.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from typing import Any

# tests/ is not a package: importing sibling conftest by name would be
# collision-prone across leaf test dirs, so the fixture type is aliased here.
Runner = Callable[..., subprocess.CompletedProcess[str]]

VALID_STATUSES = {"PASS", "FAIL", "WARN", "N/A"}
EXPECTED_CHECK_IDS = {
    "repo-root",
    "git",
    "uv",
    "python",
    "claude-cli",
    "uv-sync",
    "just",
    "shellcheck",
    "gitleaks",
    "kubectl",
    "helm",
    "k3d",
    "oasdiff",
    "plugin-bundle",
    "claude-settings",
    "hook-scripts",
    "hook-kill-switch",
    "agents",
    "skills-manifest",
    "worktree-tool",
}


def _report(stdout: str) -> dict[str, Any]:
    report = json.loads(stdout)
    assert isinstance(report, dict)
    return report


def _check(report: dict[str, Any], check_id: str) -> dict[str, str]:
    matches = [c for c in report["checks"] if c["id"] == check_id]
    assert len(matches) == 1, f"expected exactly one {check_id!r} check, got {matches!r}"
    return matches[0]


def test_help_exits_zero_and_is_honest_about_windows(run_bootstrap: Runner) -> None:
    result = run_bootstrap(["--help"])
    assert result.returncode == 0
    assert "Usage: sh scripts/bootstrap-claude.sh" in result.stdout
    assert "WSL" in result.stdout
    assert "cmd.exe" in result.stdout  # native Windows explicitly unsupported


def test_unknown_option_is_usage_error_exit_2(run_bootstrap: Runner) -> None:
    result = run_bootstrap(["--frobnicate"])
    assert result.returncode == 2
    assert "unknown option" in result.stderr
    assert "saena.bootstrap-report/v1" not in result.stdout


def test_check_human_table_shape(run_bootstrap: Runner) -> None:
    result = run_bootstrap(["--check"])
    assert result.returncode == 0
    assert "CHECK" in result.stdout and "STATUS" in result.stdout and "DETAIL" in result.stdout
    assert "repo-root" in result.stdout
    assert "hook-kill-switch" in result.stdout
    assert result.stdout.rstrip().endswith("(exit 0)")


def test_check_is_cwd_independent(run_bootstrap: Runner) -> None:
    result = run_bootstrap(["--check"], cwd="/")
    assert result.returncode == 0
    assert "repo root: " in result.stdout


def test_check_json_schema_and_exit_code_field(run_bootstrap: Runner) -> None:
    result = run_bootstrap(["--check", "--json"])
    assert result.returncode == 0
    report = _report(result.stdout)
    assert report["schema_version"] == "saena.bootstrap-report/v1"
    assert report["mode"] == "check"
    assert report["exit_code"] == result.returncode
    assert isinstance(report["checks"], list)
    for check in report["checks"]:
        assert set(check.keys()) == {"id", "status", "detail", "remedy"}
        assert check["status"] in VALID_STATUSES
    assert {c["id"] for c in report["checks"]} == EXPECTED_CHECK_IDS


def test_json_report_never_leaks_env_secrets(run_bootstrap: Runner) -> None:
    # Secret-shaped values are constructed at runtime so no secret-shaped
    # literal is committed to the repository (gitleaks runs in CI).
    fake_key = "sk-" + "live-" + "deadbeefcafe" * 2
    fake_aws = "AKIA" + "FIXTUREFAKE0" + "0000"
    extra = {"SAENA_FAKE_TOKEN": fake_key, "AWS_SECRET_ACCESS_KEY": fake_aws}
    for args in (["--check", "--json"], ["--check"]):
        result = run_bootstrap(args, extra_env=extra)
        combined = result.stdout + result.stderr
        assert fake_key not in combined
        assert fake_aws not in combined


def test_missing_uv_fails_with_actionable_remedy(run_bootstrap: Runner) -> None:
    result = run_bootstrap(["--check", "--json"], shims="no-uv")
    assert result.returncode == 1
    report = _report(result.stdout)
    assert report["exit_code"] == 1
    uv_check = _check(report, "uv")
    assert uv_check["status"] == "FAIL"
    assert uv_check["remedy"], "FAIL check must carry an actionable remedy"
    # dependent checks degrade honestly instead of lying
    assert _check(report, "python")["status"] == "N/A"
    human = run_bootstrap(["--check"], shims="no-uv")
    assert human.returncode == 1
    assert "-> remedy:" in human.stdout


def test_missing_claude_fails_with_actionable_remedy(run_bootstrap: Runner) -> None:
    result = run_bootstrap(["--check", "--json"], shims="no-claude")
    assert result.returncode == 1
    claude_check = _check(_report(result.stdout), "claude-cli")
    assert claude_check["status"] == "FAIL"
    assert claude_check["remedy"]


def test_exit_codes_are_distinct(run_bootstrap: Runner) -> None:
    assert run_bootstrap(["--check"]).returncode == 0  # healthy
    assert run_bootstrap(["--check"], shims="no-uv").returncode == 1  # failed checks
    assert run_bootstrap(["--nope"]).returncode == 2  # usage


def test_report_only_tools_never_claim_local_coverage(run_bootstrap: Runner) -> None:
    # gitleaks & friends have no pinned uv path: with the restricted PATH the
    # report must say N/A + CI coverage, and must never claim a scan ran.
    result = run_bootstrap(["--check", "--json"])
    report = _report(result.stdout)
    gitleaks = _check(report, "gitleaks")
    assert gitleaks["status"] == "N/A"
    assert "CI" in gitleaks["detail"]
    combined = result.stdout.lower()
    assert "scan passed" not in combined
    assert "scan ran" not in combined

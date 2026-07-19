"""CLI dispatch — mission invocations, exit-code map, mode matrix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _pilot_fixtures import run_git
from saena_pilot import cli
from saena_pilot.cli import (
    EXIT_BOUNDARY_VIOLATION,
    EXIT_CONTRACT_INCOMPLETE,
    EXIT_OK,
    EXIT_RUNTIME_ERROR,
    EXIT_USAGE,
    EXIT_VALIDATION_FAILED,
    main,
)

DOMAIN = "https://customer.example"


def _audit(customer_repo: Path, *extra: str) -> list[str]:
    return ["--customer-repo", str(customer_repo), "--domain", DOMAIN, "--mode", "audit", *extra]


def _porcelain(repo: Path) -> str:
    result = run_git(repo, "status", "--porcelain")
    assert result.returncode == 0
    return result.stdout


class TestExitCodeMap:
    def test_constants_are_distinct_and_frozen(self) -> None:
        codes = [
            cli.EXIT_OK,
            cli.EXIT_VALIDATION_FAILED,
            cli.EXIT_USAGE,
            cli.EXIT_CONTRACT_INCOMPLETE,
            cli.EXIT_BUNDLE_INVALID,
            cli.EXIT_BOUNDARY_VIOLATION,
            cli.EXIT_RUNTIME_ERROR,
        ]
        assert codes == [0, 1, 2, 3, 4, 5, 6]


class TestUsage:
    def test_help_exits_ok(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--help"]) == EXIT_OK
        assert "--customer-repo" in capsys.readouterr().out

    def test_missing_mode_is_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--customer-repo", "/x", "--domain", DOMAIN]) == EXIT_USAGE
        capsys.readouterr()

    def test_unknown_mode_is_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--mode", "deploy"]) == EXIT_USAGE
        capsys.readouterr()

    def test_audit_requires_customer_repo_and_domain(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--mode", "audit"]) == EXIT_USAGE
        err = capsys.readouterr().err
        assert "--customer-repo" in err and "--domain" in err

    def test_run_id_invalid_for_start_modes(
        self, rapid7_root: Path, customer_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(_audit(customer_repo, "--run-id", "abc")) == EXIT_USAGE
        capsys.readouterr()

    def test_verify_requires_run_id(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--mode", "verify"]) == EXIT_USAGE
        capsys.readouterr()

    def test_customer_repo_invalid_for_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--mode", "status", "--customer-repo", "/x"]) == EXIT_USAGE
        capsys.readouterr()


class TestMissionInvocations:
    def test_mission_audit_invocation_dry_run(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # `saena-pilot --customer-repo "/abs/path" --domain "https://…" --mode audit`
        exit_code = main(_audit(customer_repo, "--dry-run"))
        assert exit_code == EXIT_OK
        out = capsys.readouterr().out
        assert "audit report" in out
        assert "dry-run — NOT executed" in out
        assert "--add-dir" in out

    def test_mission_audit_invocation_launches_stub(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        stub_claude: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = main(_audit(customer_repo))
        assert exit_code == EXIT_OK
        recorded = stub_claude.read_text(encoding="utf-8").splitlines()
        assert recorded == ["--add-dir", str(customer_repo.resolve())]
        capsys.readouterr()

    def test_dry_run_does_not_execute(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        stub_claude: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(_audit(customer_repo, "--dry-run")) == EXIT_OK
        assert not stub_claude.exists()  # stub was never invoked
        capsys.readouterr()

    def test_json_dry_run_argv_preserves_spaces_unicode(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(_audit(customer_repo, "--dry-run", "--json")) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert payload["launch"]["argv"] == [
            "claude",
            "--add-dir",
            str(customer_repo.resolve()),
        ]
        assert payload["launch"]["cwd"] == str(rapid7_root)
        assert payload["report"]["contract_complete"] is False


class TestExitPaths:
    def test_boundary_violation_exit(
        self, rapid7_root: Path, pilot_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(_audit(rapid7_root, "--dry-run")) == EXIT_BOUNDARY_VIOLATION
        capsys.readouterr()

    def test_validation_failed_exit_on_relative_path(
        self, rapid7_root: Path, pilot_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        argv = ["--customer-repo", "rel", "--domain", DOMAIN, "--mode", "audit"]
        assert main(argv) == EXIT_VALIDATION_FAILED
        capsys.readouterr()

    def test_validation_failed_exit_on_http_domain(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        argv = [
            "--customer-repo",
            str(customer_repo),
            "--domain",
            "http://customer.example",
            "--mode",
            "audit",
        ]
        assert main(argv) == EXIT_VALIDATION_FAILED
        capsys.readouterr()

    def test_plan_without_contract_is_contract_incomplete(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        argv = [
            "--customer-repo",
            str(customer_repo),
            "--domain",
            DOMAIN,
            "--mode",
            "plan",
            "--dry-run",
        ]
        assert main(argv) == EXIT_CONTRACT_INCOMPLETE
        err = capsys.readouterr().err
        assert "1." in err and "8." in err  # numbered questions listed

    def test_implement_blocks_on_dirty_tree(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        complete_intake: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (customer_repo / "wip.txt").write_text("dirty", encoding="utf-8")
        argv = [
            "--customer-repo",
            str(customer_repo),
            "--domain",
            DOMAIN,
            "--mode",
            "implement",
            "--intake",
            str(complete_intake),
            "--dry-run",
        ]
        assert main(argv) == EXIT_VALIDATION_FAILED
        assert "dirty_tree" in capsys.readouterr().err

    def test_launch_failure_maps_to_runtime_error(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def failing_runner(argv, cwd, env):  # type: ignore[no-untyped-def]
            return 17

        assert main(_audit(customer_repo), launch_runner=failing_runner) == EXIT_RUNTIME_ERROR
        capsys.readouterr()

    def test_outside_rapid7_checkout_rejected(
        self,
        tmp_path: Path,
        customer_repo: Path,
        pilot_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        monkeypatch.chdir(outside)
        assert main(_audit(customer_repo, "--dry-run")) == EXIT_VALIDATION_FAILED
        assert "RAPID-7" in capsys.readouterr().err

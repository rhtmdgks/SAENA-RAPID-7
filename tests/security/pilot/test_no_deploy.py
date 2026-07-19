"""Attack 13 — no unapproved production commands.

The pilot only ever launches `claude --add-dir <dir>` from the RAPID-7 root;
it never renders or executes a deploy/push/merge/publish command in any mode.
audit/preflight/plan/verify/status/resume never write to the customer; only
`implement` creates a customer worktree, and even then it never deploys.

Every test asserts a concrete outcome: the exact rendered argv, the absence of
forbidden tokens across all evidence/report artifacts, a recorded stub launch,
or a typed `BoundaryViolationError` for misuse.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _sec_fixtures import read_all_run_text
from saena_pilot.cli import EXIT_OK, main
from saena_pilot.errors import BoundaryViolationError
from saena_pilot.launcher import render_launch
from saena_pilot.models import Mode
from saena_pilot.runstore import list_runs, run_dir
from saena_pilot.worktree import create_customer_worktree, worktree_path

DOMAIN = "https://customer.example"
FORBIDDEN = (
    "deploy",
    "push",
    "merge",
    "publish",
    "kubectl",
    "helm",
    "rollout",
    "--force",
    "git push",
)


def _start(customer: Path, mode: str, *extra: str) -> list[str]:
    return [
        "--customer-repo",
        str(customer),
        "--domain",
        DOMAIN,
        "--mode",
        mode,
        "--dry-run",
        *extra,
    ]


class TestLaunchArgvIsClaudeOnly:
    def test_audit_launch_argv_is_add_dir_only(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(_start(customer_repo, "audit")) == EXIT_OK
        run_id = list_runs()[-1]
        evidence = (run_dir(run_id) / "events.jsonl").read_text(encoding="utf-8")
        assert '"claude"' in evidence
        assert '"--add-dir"' in evidence
        for token in FORBIDDEN:
            assert token not in evidence, f"forbidden token {token!r} in launch evidence"
        capsys.readouterr()

    def test_render_audit_argv_exact(self, rapid7_root: Path, customer_repo: Path) -> None:
        spec = render_launch(
            mode=Mode.AUDIT,
            rapid7_root=rapid7_root,
            customer_root=customer_repo,
            worktree=None,
            run_id="r1",
            run_dir=Path("/tmp/run"),
        )
        assert spec.argv == ("claude", "--add-dir", str(customer_repo))
        assert spec.cwd == rapid7_root  # launched FROM RAPID-7, hooks stay active

    def test_render_plan_argv_exact(self, rapid7_root: Path, customer_repo: Path) -> None:
        spec = render_launch(
            mode=Mode.PLAN,
            rapid7_root=rapid7_root,
            customer_root=customer_repo,
            worktree=None,
            run_id="r2",
            run_dir=Path("/tmp/run"),
        )
        assert spec.argv[0] == "claude"
        assert all(tok not in spec.argv for tok in FORBIDDEN)

    def test_render_implement_uses_worktree_not_root(
        self, rapid7_root: Path, customer_repo: Path, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "wt"
        spec = render_launch(
            mode=Mode.IMPLEMENT,
            rapid7_root=rapid7_root,
            customer_root=customer_repo,
            worktree=worktree,
            run_id="r3",
            run_dir=Path("/tmp/run"),
        )
        assert spec.argv == ("claude", "--add-dir", str(worktree))
        assert str(customer_repo) not in spec.argv  # never the raw customer root
        assert all(tok not in spec.argv for tok in FORBIDDEN)


class TestNonLaunchingModes:
    def test_verify_never_launches(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        stub_bin: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(_start(customer_repo, "audit")) == EXIT_OK
        run_id = list_runs()[-1]
        capsys.readouterr()
        # verify uses only the recorded run; it renders/executes NO claude launch
        # and no docker probe (both are start-mode concerns). Clear the markers
        # the audit start-mode legitimately created, then assert verify adds none.
        (stub_bin / "claude.txt").unlink(missing_ok=True)
        (stub_bin / "docker.txt").unlink(missing_ok=True)
        main(["--mode", "verify", "--run-id", run_id])
        assert not (stub_bin / "claude.txt").exists()
        assert not (stub_bin / "docker.txt").exists()
        capsys.readouterr()

    def test_status_never_launches(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        stub_bin: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        main(["--mode", "status"])
        assert not (stub_bin / "claude.txt").exists()
        assert not (stub_bin / "docker.txt").exists()
        capsys.readouterr()

    @pytest.mark.parametrize("mode", [Mode.VERIFY, Mode.RESUME, Mode.STATUS, Mode.PREFLIGHT])
    def test_non_launching_modes_flagged(self, mode: Mode) -> None:
        assert mode.launches_claude is False


class TestRenderLaunchMisuseRefused:
    def test_read_mode_with_worktree_refused(
        self, rapid7_root: Path, customer_repo: Path, tmp_path: Path
    ) -> None:
        with pytest.raises(BoundaryViolationError):
            render_launch(
                mode=Mode.AUDIT,
                rapid7_root=rapid7_root,
                customer_root=customer_repo,
                worktree=tmp_path / "wt",
                run_id="r",
                run_dir=Path("/tmp/run"),
            )

    def test_implement_without_worktree_refused(
        self, rapid7_root: Path, customer_repo: Path
    ) -> None:
        with pytest.raises(BoundaryViolationError):
            render_launch(
                mode=Mode.IMPLEMENT,
                rapid7_root=rapid7_root,
                customer_root=customer_repo,
                worktree=None,
                run_id="r",
                run_dir=Path("/tmp/run"),
            )

    def test_non_launching_mode_render_refused(
        self, rapid7_root: Path, customer_repo: Path
    ) -> None:
        with pytest.raises(BoundaryViolationError):
            render_launch(
                mode=Mode.VERIFY,
                rapid7_root=rapid7_root,
                customer_root=customer_repo,
                worktree=None,
                run_id="r",
                run_dir=Path("/tmp/run"),
            )


class TestOnlyImplementCreatesWorktree:
    @pytest.mark.parametrize("mode", [Mode.AUDIT, Mode.PLAN, Mode.PREFLIGHT])
    def test_read_mode_cannot_create_worktree(
        self, mode: Mode, rapid7_root: Path, customer_repo: Path
    ) -> None:
        with pytest.raises(BoundaryViolationError):
            create_customer_worktree(customer_repo, "run-x", mode=mode)

    def test_worktree_target_is_outside_customer_root(self, customer_repo: Path) -> None:
        target = worktree_path(customer_repo, "run-x")
        # sibling `<name>.saena-worktrees/<run>` — never inside the customer root.
        assert customer_repo not in target.parents
        assert target.parent.parent == customer_repo.parent


class TestNoForbiddenTokensAnywhere:
    def test_all_run_artifacts_free_of_deploy_tokens(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(_start(customer_repo, "audit")) == EXIT_OK
        blob = read_all_run_text(pilot_home)
        for token in ("kubectl", "helm", "git push", "rollout", "--force"):
            assert token not in blob, f"forbidden token {token!r} in run artifacts"
        capsys.readouterr()

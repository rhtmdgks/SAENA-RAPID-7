"""Attack 14 & 16 — write isolation + no accidental customer-source copy.

Claims proven:
- Read modes (audit/plan, dry-run) leave the customer `git status --porcelain`
  completely unchanged and never write under the customer root.
- `implement` writes ONLY inside a dedicated worktree that lives OUTSIDE the
  customer root; the customer root's own working tree stays clean.
- After an audit + dry-run implement, the RAPID-7 `git status --porcelain`
  shows NOTHING added — no vendored customer content. Run metadata lives only
  under SAENA_PILOT_HOME.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _sec_fixtures import commit_all, make_git_repo, porcelain
from saena_pilot.cli import EXIT_OK, main
from saena_pilot.runstore import list_runs, run_dir
from saena_pilot.worktree import worktree_container

DOMAIN = "https://customer.example"
CUSTOMER_MARK = "SUPER-SECRET-CUSTOMER-CONTENT-42"


def _mode(customer: Path, mode: str, *extra: str) -> list[str]:
    return ["--customer-repo", str(customer), "--domain", DOMAIN, "--mode", mode, *extra]


class TestReadModesLeaveCustomerUnchanged:
    @pytest.mark.parametrize("mode", ["audit", "plan"])
    def test_read_mode_customer_porcelain_unchanged(
        self,
        mode: str,
        rapid7_root: Path,
        customer_repo: Path,
        complete_intake: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        before = porcelain(customer_repo)
        assert before == ""  # clean to start
        argv = _mode(customer_repo, mode, "--dry-run", "--intake", str(complete_intake))
        assert main(argv) == EXIT_OK
        assert porcelain(customer_repo) == "", f"{mode} wrote to the customer tree!"
        capsys.readouterr()

    def test_read_mode_creates_no_worktree(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(_mode(customer_repo, "audit", "--dry-run")) == EXIT_OK
        assert not worktree_container(customer_repo).exists()
        capsys.readouterr()

    def test_implement_dry_run_creates_no_worktree(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        complete_intake: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        argv = _mode(customer_repo, "implement", "--dry-run", "--intake", str(complete_intake))
        assert main(argv) == EXIT_OK
        assert not worktree_container(customer_repo).exists()
        assert porcelain(customer_repo) == ""
        capsys.readouterr()


class TestImplementWorktreeIsIsolated:
    def test_implement_writes_only_outside_customer_root(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        complete_intake: Path,
        pilot_home: Path,
        stub_bin: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        argv = _mode(customer_repo, "implement", "--intake", str(complete_intake))
        assert main(argv) == EXIT_OK
        capsys.readouterr()
        container = worktree_container(customer_repo)
        # The dedicated worktree is a SIBLING of the customer root, never inside.
        assert container.exists()
        assert container.parent == customer_repo.parent
        assert customer_repo not in container.parents
        # The customer root's own tree is untouched.
        assert porcelain(customer_repo) == ""

    def test_implement_launch_targets_worktree(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        complete_intake: Path,
        pilot_home: Path,
        stub_bin: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        argv = _mode(customer_repo, "implement", "--intake", str(complete_intake))
        assert main(argv) == EXIT_OK
        capsys.readouterr()
        recorded = (stub_bin / "claude.txt").read_text(encoding="utf-8").splitlines()
        assert recorded[0] == "--add-dir"
        # add-dir points at the worktree (inside the container), not the root.
        assert str(worktree_container(customer_repo)) in recorded[1]
        assert recorded[1] != str(customer_repo)


class TestNoCustomerCopyIntoRapid7:
    def test_rapid7_porcelain_unchanged_after_audit_and_implement_dryrun(
        self,
        rapid7_root: Path,
        tmp_path: Path,
        complete_intake: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Customer repo carries a uniquely-marked file we can hunt for.
        customer = make_git_repo(tmp_path / "cust-mark")
        (customer / "secret.txt").write_text(CUSTOMER_MARK + "\n", encoding="utf-8")
        commit_all(customer, "customer content")
        rapid7_before = porcelain(rapid7_root)

        assert main(_mode(customer, "audit", "--dry-run")) == EXIT_OK
        capsys.readouterr()
        assert (
            main(_mode(customer, "implement", "--dry-run", "--intake", str(complete_intake)))
            == EXIT_OK
        )
        capsys.readouterr()

        # RAPID-7 tree shows nothing new (no vendored customer copy).
        assert porcelain(rapid7_root) == rapid7_before == ""
        # And the customer marker exists nowhere inside the RAPID-7 tree.
        for path in rapid7_root.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                assert CUSTOMER_MARK not in path.read_text(encoding="utf-8", errors="replace")

    def test_run_metadata_lives_only_under_pilot_home(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(_mode(customer_repo, "audit", "--dry-run")) == EXIT_OK
        capsys.readouterr()
        run_id = list_runs()[-1]
        directory = run_dir(run_id)
        # The run dir resolves under SAENA_PILOT_HOME, not under either repo.
        assert str(pilot_home) in str(directory.resolve())
        assert (directory / "run.json").is_file()
        assert (directory / "events.jsonl").is_file()
        # No run.json anywhere under the RAPID-7 or customer trees.
        assert not any(rapid7_root.rglob("run.json"))
        assert not any(customer_repo.rglob("run.json"))

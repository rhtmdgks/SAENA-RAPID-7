"""Attack 1/2/15 — customer-path escape, symlink escape, protected-path write.

Every case asserts a concrete outcome: the typed exception class
(`BoundaryViolationError` / `ValidationFailedError`) AND the CLI exit code
(`EXIT_BOUNDARY_VIOLATION` = 5, `EXIT_VALIDATION_FAILED` = 1).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from _sec_fixtures import make_git_repo
from saena_pilot.boundary import validate_customer_repo
from saena_pilot.cli import EXIT_BOUNDARY_VIOLATION, EXIT_OK, EXIT_VALIDATION_FAILED, main
from saena_pilot.errors import BoundaryViolationError, ValidationFailedError
from saena_pilot.models import Mode
from saena_pilot.runstore import ensure_store_outside_repos

DOMAIN = "https://customer.example"


def _audit(customer: str) -> list[str]:
    return ["--customer-repo", customer, "--domain", DOMAIN, "--mode", "audit", "--dry-run"]


class TestRawShapeRejected:
    def test_relative_path_rejected_before_resolution(self, rapid7_root: Path) -> None:
        with pytest.raises(ValidationFailedError):
            validate_customer_repo("relative/path", rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_relative_path_cli_exit_validation_failed(
        self, rapid7_root: Path, pilot_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(_audit("relative/path")) == EXIT_VALIDATION_FAILED
        capsys.readouterr()

    def test_nonexistent_path_rejected(self, rapid7_root: Path, tmp_path: Path) -> None:
        with pytest.raises(ValidationFailedError):
            validate_customer_repo(
                str(tmp_path / "does-not-exist"), rapid7_root=rapid7_root, mode=Mode.AUDIT
            )

    def test_file_not_dir_rejected(self, rapid7_root: Path, tmp_path: Path) -> None:
        f = tmp_path / "afile"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(ValidationFailedError):
            validate_customer_repo(str(f), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_non_git_dir_rejected(self, rapid7_root: Path, tmp_path: Path) -> None:
        d = tmp_path / "plain-dir"
        d.mkdir()
        with pytest.raises(ValidationFailedError):
            validate_customer_repo(str(d), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_repo_subdir_not_root_rejected(self, rapid7_root: Path, customer_repo: Path) -> None:
        sub = customer_repo / "nested-subdir"
        sub.mkdir()
        with pytest.raises(ValidationFailedError):
            validate_customer_repo(str(sub), rapid7_root=rapid7_root, mode=Mode.AUDIT)


class TestDotDotTraversal:
    def test_dotdot_resolving_to_rapid7_root_is_boundary_violation(self, rapid7_root: Path) -> None:
        # <rapid7>/../<name> normalizes (via realpath) back to the RAPID-7 root.
        escaped = os.path.join(str(rapid7_root), "..", rapid7_root.name)
        with pytest.raises(BoundaryViolationError):
            validate_customer_repo(escaped, rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_dotdot_resolving_inside_rapid7_is_boundary_violation(self, rapid7_root: Path) -> None:
        inside = os.path.join(str(rapid7_root), "tools", "..", ".claude")
        with pytest.raises(BoundaryViolationError):
            validate_customer_repo(inside, rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_dotdot_cli_exit_boundary_violation(
        self, rapid7_root: Path, pilot_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        escaped = os.path.join(str(rapid7_root), "..", rapid7_root.name)
        assert main(_audit(escaped)) == EXIT_BOUNDARY_VIOLATION
        capsys.readouterr()

    def test_dotdot_normalizes_and_accepts_legit_external_repo(
        self, rapid7_root: Path, customer_repo: Path
    ) -> None:
        # A `..` that normalizes to a legitimate EXTERNAL repo must be accepted.
        normalized = os.path.join(str(customer_repo), "subdir", "..")
        (customer_repo / "subdir").mkdir()
        report = validate_customer_repo(normalized, rapid7_root=rapid7_root, mode=Mode.AUDIT)
        assert report.customer_root == Path(os.path.realpath(customer_repo))


class TestContainment:
    def test_customer_equals_rapid7_root(self, rapid7_root: Path) -> None:
        with pytest.raises(BoundaryViolationError):
            validate_customer_repo(str(rapid7_root), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_customer_nested_inside_rapid7(self, rapid7_root: Path) -> None:
        nested = make_git_repo(rapid7_root / "vendored-customer")
        with pytest.raises(BoundaryViolationError):
            validate_customer_repo(str(nested), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_rapid7_nested_inside_customer(self, rapid7_root: Path, tmp_path: Path) -> None:
        # Build an outer customer repo whose tree physically contains rapid7_root.
        outer = make_git_repo(rapid7_root.parent)
        with pytest.raises(BoundaryViolationError):
            validate_customer_repo(str(outer), rapid7_root=rapid7_root, mode=Mode.AUDIT)


class TestSymlinkEscape:
    def test_symlink_to_rapid7_root_rejected_after_realpath(
        self, rapid7_root: Path, tmp_path: Path
    ) -> None:
        link = tmp_path / "customer-link"
        link.symlink_to(rapid7_root, target_is_directory=True)
        with pytest.raises(BoundaryViolationError):
            validate_customer_repo(str(link), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_symlink_into_rapid7_subdir_rejected_after_realpath(
        self, rapid7_root: Path, tmp_path: Path
    ) -> None:
        link = tmp_path / "customer-link-2"
        link.symlink_to(rapid7_root / ".claude", target_is_directory=True)
        with pytest.raises(BoundaryViolationError):
            validate_customer_repo(str(link), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_symlink_escape_cli_exit_boundary_violation(
        self,
        rapid7_root: Path,
        tmp_path: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        link = tmp_path / "customer-link-3"
        link.symlink_to(rapid7_root, target_is_directory=True)
        assert main(_audit(str(link))) == EXIT_BOUNDARY_VIOLATION
        capsys.readouterr()

    def test_symlink_to_legit_external_repo_accepted(
        self, rapid7_root: Path, customer_repo: Path, tmp_path: Path
    ) -> None:
        link = tmp_path / "ok-link"
        link.symlink_to(customer_repo, target_is_directory=True)
        report = validate_customer_repo(str(link), rapid7_root=rapid7_root, mode=Mode.AUDIT)
        assert report.customer_root == Path(os.path.realpath(customer_repo))


class TestRunStoreProtectedContainment:
    """Attack 15 — the run store may never resolve inside a protected repo."""

    def test_store_inside_rapid7_refused(
        self, rapid7_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAENA_PILOT_HOME", str(rapid7_root / ".saena"))
        with pytest.raises(ValidationFailedError):
            ensure_store_outside_repos(rapid7_root, None)

    def test_store_inside_customer_refused(
        self, rapid7_root: Path, customer_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAENA_PILOT_HOME", str(customer_repo / ".saena"))
        with pytest.raises(ValidationFailedError):
            ensure_store_outside_repos(rapid7_root, customer_repo)

    def test_store_outside_both_accepted(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        # pilot_home fixture already points SAENA_PILOT_HOME outside both repos.
        store = ensure_store_outside_repos(rapid7_root, customer_repo)
        real = Path(os.path.realpath(store))
        assert Path(os.path.realpath(rapid7_root)) not in real.parents
        assert real != Path(os.path.realpath(rapid7_root))
        assert Path(os.path.realpath(customer_repo)) not in real.parents


class TestAcceptedBaseline:
    def test_normal_customer_audit_exits_ok(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(_audit(str(customer_repo))) == EXIT_OK
        capsys.readouterr()

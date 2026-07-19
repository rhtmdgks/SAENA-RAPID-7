"""Boundary matrix — customer-repo validation, fail-closed."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from _pilot_fixtures import make_git_repo, run_git
from saena_pilot.boundary import validate_customer_repo
from saena_pilot.errors import BoundaryViolationError, ValidationFailedError
from saena_pilot.models import Mode, Severity


def _codes(report) -> set[str]:  # type: ignore[no-untyped-def]
    return {finding.code for finding in report.findings}


class TestShapeFailures:
    def test_relative_path_rejected_before_resolution(self, rapid7_root: Path) -> None:
        with pytest.raises(ValidationFailedError, match="absolute"):
            validate_customer_repo("relative/path", rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_missing_path_rejected(self, rapid7_root: Path, tmp_path: Path) -> None:
        with pytest.raises(ValidationFailedError, match="does not exist"):
            validate_customer_repo(str(tmp_path / "nope"), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_file_not_directory_rejected(self, rapid7_root: Path, tmp_path: Path) -> None:
        file_path = tmp_path / "a-file"
        file_path.write_text("x", encoding="utf-8")
        with pytest.raises(ValidationFailedError, match="not a directory"):
            validate_customer_repo(str(file_path), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_non_git_directory_rejected(self, rapid7_root: Path, tmp_path: Path) -> None:
        plain = tmp_path / "plain-dir"
        plain.mkdir()
        with pytest.raises(ValidationFailedError, match="not a git repository"):
            validate_customer_repo(str(plain), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_subdir_of_customer_repo_rejected_not_root(
        self, rapid7_root: Path, customer_repo: Path
    ) -> None:
        sub = customer_repo / "packages"
        sub.mkdir()
        with pytest.raises(ValidationFailedError, match="ROOT"):
            validate_customer_repo(str(sub), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_repo_without_commits_rejected(self, rapid7_root: Path, tmp_path: Path) -> None:
        empty = tmp_path / "empty-repo"
        empty.mkdir()
        assert run_git(empty, "init", "-q").returncode == 0
        with pytest.raises(ValidationFailedError, match="HEAD"):
            validate_customer_repo(str(empty), rapid7_root=rapid7_root, mode=Mode.AUDIT)


class TestContainmentViolations:
    def test_same_repo_rejected(self, rapid7_root: Path) -> None:
        with pytest.raises(BoundaryViolationError, match="RAPID-7 repository itself"):
            validate_customer_repo(str(rapid7_root), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_nested_inside_rapid7_rejected(self, rapid7_root: Path) -> None:
        nested = make_git_repo(rapid7_root / "vendor" / "inner")
        with pytest.raises(BoundaryViolationError, match="nested inside the RAPID-7"):
            validate_customer_repo(str(nested), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_rapid7_nested_inside_customer_rejected(self, tmp_path: Path) -> None:
        outer = make_git_repo(tmp_path / "outer")
        inner_rapid7 = make_git_repo(outer / "vendor" / "rapid7")
        with pytest.raises(BoundaryViolationError, match="nested inside the customer"):
            validate_customer_repo(str(outer), rapid7_root=inner_rapid7, mode=Mode.AUDIT)

    def test_symlink_to_rapid7_escape_rejected(self, rapid7_root: Path, tmp_path: Path) -> None:
        link = tmp_path / "innocent-looking"
        link.symlink_to(rapid7_root)
        with pytest.raises(BoundaryViolationError):
            validate_customer_repo(str(link), rapid7_root=rapid7_root, mode=Mode.AUDIT)

    def test_dotdot_traversal_normalized_before_checks(
        self, rapid7_root: Path, customer_repo: Path
    ) -> None:
        # A ".."-laden spelling of the RAPID-7 root must still be caught.
        tricky = str(customer_repo / ".." / rapid7_root.name)
        assert os.path.realpath(tricky) == str(rapid7_root)
        with pytest.raises(BoundaryViolationError):
            validate_customer_repo(tricky, rapid7_root=rapid7_root, mode=Mode.AUDIT)


class TestAcceptedRepos:
    def test_clean_repo_accepted_with_no_findings(
        self, rapid7_root: Path, customer_repo: Path
    ) -> None:
        report = validate_customer_repo(
            str(customer_repo), rapid7_root=rapid7_root, mode=Mode.AUDIT
        )
        assert report.findings == ()
        assert not report.blocked
        assert len(report.head_sha) == 40

    def test_spaces_and_unicode_path_supported(
        self, rapid7_root: Path, customer_repo: Path
    ) -> None:
        # The fixture path contains spaces, Hangul, and Greek.
        assert " " in customer_repo.name and "저장소" in customer_repo.name
        report = validate_customer_repo(
            str(customer_repo), rapid7_root=rapid7_root, mode=Mode.AUDIT
        )
        assert report.customer_root == Path(os.path.realpath(customer_repo))

    def test_symlink_to_legit_repo_resolves_and_passes(
        self, rapid7_root: Path, customer_repo: Path, tmp_path: Path
    ) -> None:
        link = tmp_path / "link-to-customer"
        link.symlink_to(customer_repo)
        report = validate_customer_repo(str(link), rapid7_root=rapid7_root, mode=Mode.AUDIT)
        assert report.customer_root == Path(os.path.realpath(customer_repo))


class TestStateFindings:
    def test_dirty_tree_warns_in_audit(self, rapid7_root: Path, customer_repo: Path) -> None:
        (customer_repo / "wip.txt").write_text("dirty", encoding="utf-8")
        report = validate_customer_repo(
            str(customer_repo), rapid7_root=rapid7_root, mode=Mode.AUDIT
        )
        assert "dirty_tree" in _codes(report)
        assert not report.blocked

    def test_dirty_tree_blocks_in_implement(self, rapid7_root: Path, customer_repo: Path) -> None:
        (customer_repo / "wip.txt").write_text("dirty", encoding="utf-8")
        report = validate_customer_repo(
            str(customer_repo), rapid7_root=rapid7_root, mode=Mode.IMPLEMENT
        )
        assert report.blocked
        assert {f.code for f in report.block_findings} == {"dirty_tree"}

    def test_detached_head_warns_in_preflight_blocks_in_implement(
        self, rapid7_root: Path, customer_repo: Path
    ) -> None:
        assert run_git(customer_repo, "checkout", "-q", "--detach").returncode == 0
        warn = validate_customer_repo(
            str(customer_repo), rapid7_root=rapid7_root, mode=Mode.PREFLIGHT
        )
        assert "detached_head" in _codes(warn)
        assert not warn.blocked
        block = validate_customer_repo(
            str(customer_repo), rapid7_root=rapid7_root, mode=Mode.IMPLEMENT
        )
        assert block.blocked

    def test_nested_repo_detected(self, rapid7_root: Path, customer_repo: Path) -> None:
        make_git_repo(customer_repo / "vendor" / "lib")
        report = validate_customer_repo(
            str(customer_repo), rapid7_root=rapid7_root, mode=Mode.PREFLIGHT
        )
        nested = [f for f in report.findings if f.code == "nested_repos"]
        assert nested and nested[0].context["nested"] == [str(Path("vendor") / "lib")]
        assert nested[0].severity is Severity.WARN

    def test_nested_repo_blocks_implement(self, rapid7_root: Path, customer_repo: Path) -> None:
        make_git_repo(customer_repo / "vendor" / "lib")
        # Commit the nested repo pointer-free state is impossible; the dirty
        # finding may co-occur — only severity classification matters here.
        report = validate_customer_repo(
            str(customer_repo), rapid7_root=rapid7_root, mode=Mode.IMPLEMENT
        )
        assert any(
            f.code == "nested_repos" and f.severity is Severity.BLOCK for f in report.findings
        )

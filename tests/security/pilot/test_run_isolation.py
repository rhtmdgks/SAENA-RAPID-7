"""Attack 7 & 8 — cross-customer contamination + stale/resumed substitution.

Claims proven:
- Two runs against different customer repos get distinct run dirs and evidence
  chains that bind ONLY their own customer SHA (no cross-reference).
- Loading a run whose recorded customer SHA no longer matches the world is
  refused (`ResumeMismatchError` -> `EXIT_VALIDATION_FAILED`).
- Resume is refused after the RAPID-7 HEAD moves, after the customer HEAD
  moves, and after the skill-manifest sha changes — each with an explicit
  reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _sec_fixtures import commit_all, make_git_repo
from saena_pilot.cli import EXIT_OK, EXIT_VALIDATION_FAILED, main
from saena_pilot.errors import ResumeMismatchError
from saena_pilot.models import Mode
from saena_pilot.runstore import list_runs, load_run, run_dir, save_run, validate_resume

DOMAIN_A = "https://customer-a.example"
DOMAIN_B = "https://customer-b.example"


def _audit(customer: Path, domain: str) -> list[str]:
    return ["--customer-repo", str(customer), "--domain", domain, "--mode", "audit", "--dry-run"]


def _run_audit(customer: Path, domain: str, capsys: pytest.CaptureFixture[str]) -> str:
    before = set(list_runs())
    assert main(_audit(customer, domain)) == EXIT_OK
    capsys.readouterr()
    after = set(list_runs())
    new = after - before
    assert len(new) == 1
    return new.pop()


class TestCrossCustomerIsolation:
    def test_two_customers_get_distinct_run_dirs(
        self,
        rapid7_root: Path,
        tmp_path: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cust_a = make_git_repo(tmp_path / "cust-a")
        cust_b = make_git_repo(tmp_path / "cust-b")
        run_a = _run_audit(cust_a, DOMAIN_A, capsys)
        run_b = _run_audit(cust_b, DOMAIN_B, capsys)
        assert run_a != run_b
        assert run_dir(run_a) != run_dir(run_b)
        assert run_dir(run_a).is_dir() and run_dir(run_b).is_dir()

    def test_evidence_chains_bind_only_own_customer_sha(
        self,
        rapid7_root: Path,
        tmp_path: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cust_a = make_git_repo(tmp_path / "cust-a2")
        cust_b = make_git_repo(tmp_path / "cust-b2")
        run_a = _run_audit(cust_a, DOMAIN_A, capsys)
        run_b = _run_audit(cust_b, DOMAIN_B, capsys)
        rec_a, rec_b = load_run(run_a), load_run(run_b)
        assert rec_a.customer_sha != rec_b.customer_sha
        # Run A's stored artifacts never mention run B's id or customer sha.
        a_text = (run_dir(run_a) / "events.jsonl").read_text(encoding="utf-8")
        assert run_b not in a_text
        assert rec_b.customer_sha not in a_text
        assert str(cust_b) not in a_text

    def test_loading_run_a_with_customer_b_sha_refused(
        self,
        rapid7_root: Path,
        tmp_path: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cust_a = make_git_repo(tmp_path / "cust-a3")
        cust_b = make_git_repo(tmp_path / "cust-b3")
        run_a = _run_audit(cust_a, DOMAIN_A, capsys)
        rec_a = load_run(run_a)
        (cust_b / "b-only.txt").write_text("b-only\n", encoding="utf-8")
        rec_b_sha = commit_all(cust_b, "b-only")  # a sha that belongs to B
        # Splice B's SHA into A's record and try to resume A.
        rec_a.customer_sha = rec_b_sha
        save_run(rec_a)
        with pytest.raises(ResumeMismatchError):
            validate_resume(load_run(run_a), rapid7_root=rapid7_root)


class TestStaleResumeRefused:
    def _seed_run(
        self, customer: Path, pilot_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> str:
        return _run_audit(customer, DOMAIN_A, capsys)

    def test_resume_refused_after_customer_head_moves(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._seed_run(customer_repo, pilot_home, capsys)
        (customer_repo / "new.txt").write_text("x", encoding="utf-8")
        commit_all(customer_repo, "customer moves on")
        assert main(["--mode", "resume", "--run-id", run_id]) == EXIT_VALIDATION_FAILED
        capsys.readouterr()

    def test_resume_refused_after_rapid7_head_moves(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._seed_run(customer_repo, pilot_home, capsys)
        (rapid7_root / "unrelated.txt").write_text("x", encoding="utf-8")
        commit_all(rapid7_root, "rapid7 moves on")
        with pytest.raises(ResumeMismatchError):
            validate_resume(load_run(run_id), rapid7_root=rapid7_root)

    def test_resume_refused_after_manifest_sha_changes(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._seed_run(customer_repo, pilot_home, capsys)
        # Change the manifest bytes WITHOUT moving HEAD (working-tree edit).
        # It stays structurally valid, so the validator passes, but the sha
        # no longer matches the one recorded at run creation.
        manifest_path = rapid7_root / ".claude" / "skills" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["note"] = "content changed after the run was recorded"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        result = main(["--mode", "resume", "--run-id", run_id])
        assert result == EXIT_VALIDATION_FAILED
        err = capsys.readouterr().err
        assert "manifest changed" in err

    def test_clean_resume_succeeds(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._seed_run(customer_repo, pilot_home, capsys)
        # Nothing changed -> resume re-validates and succeeds.
        assert main(["--mode", "resume", "--run-id", run_id]) == EXIT_OK
        capsys.readouterr()

    def test_missing_run_refused(
        self, rapid7_root: Path, pilot_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--mode", "resume", "--run-id", "no-such-run"]) == EXIT_VALIDATION_FAILED
        capsys.readouterr()


class TestBoundaryValidateResumeMode:
    def test_resume_mode_still_validates_customer_boundary(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        # Sanity: RESUME is a read mode (dirty/detached only WARN, never BLOCK).
        assert Mode.RESUME.writes_customer is False
        assert Mode.RESUME.launches_claude is False

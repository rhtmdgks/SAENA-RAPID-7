"""Full-lifecycle CLI runs — run store contents, resume/status/verify,
no-copy invariant, implement isolation."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from _pilot_fixtures import run_git
from saena_pilot.cli import EXIT_OK, EXIT_VALIDATION_FAILED, main
from saena_pilot.evidence import verify_chain

DOMAIN = "https://customer.example"


def _start(
    mode: str,
    customer_repo: Path,
    *extra: str,
    launch_runner=None,  # type: ignore[no-untyped-def]
) -> tuple[int, dict]:  # type: ignore[type-arg]
    argv = [
        "--customer-repo",
        str(customer_repo),
        "--domain",
        DOMAIN,
        "--mode",
        mode,
        "--json",
        *extra,
    ]
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = main(argv, launch_runner=launch_runner)
    payload = json.loads(buffer.getvalue()) if buffer.getvalue().strip() else {}
    return exit_code, payload


def _porcelain(repo: Path) -> str:
    result = run_git(repo, "status", "--porcelain")
    assert result.returncode == 0
    return result.stdout


class TestPreflight:
    def test_preflight_writes_reports_and_evidence_into_store(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        (customer_repo / "CLAUDE.md").write_text("# customer rules\n", encoding="utf-8")
        exit_code, payload = _start("preflight", customer_repo)
        assert exit_code == EXIT_OK
        run_id = payload["run_id"]
        run_dir = pilot_home / "pilot-runs" / run_id
        assert (run_dir / "run.json").is_file()
        assert (run_dir / "contract.json").is_file()
        assert (run_dir / "report-preflight.json").is_file()
        assert (run_dir / "report-preflight.txt").is_file()
        verify_chain(run_dir / "events.jsonl")
        assert payload["launch"] is None  # preflight never launches

    def test_preflight_report_contains_reconciliation_and_discovery(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        (customer_repo / "CLAUDE.md").write_text("rules\n", encoding="utf-8")
        _, payload = _start("preflight", customer_repo)
        report = payload["report"]
        rec = report["stricter_rules_reconciliation"]
        assert [e["path"] for e in rec["rule_files"]] == ["CLAUDE.md"]
        assert "never executes" in rec["policy"]
        assert report["discovery"]["status"] == "UNKNOWN"
        assert report["binding"]["rapid7_sha"] != report["binding"]["customer_sha"]

    def test_dirty_customer_only_warns_in_preflight(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        (customer_repo / "wip.txt").write_text("x", encoding="utf-8")
        exit_code, payload = _start("preflight", customer_repo)
        assert exit_code == EXIT_OK
        findings = payload["report"]["boundary"]["findings"]
        assert [(f["code"], f["severity"]) for f in findings] == [("dirty_tree", "WARN")]
        # dirty tree becomes a suggested-external-operational-action
        assert any("commit or stash" in a for a in payload["report"]["suggested_human_actions"])


class TestNoCopyInvariant:
    def test_audit_leaves_both_repos_untouched(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        rapid7_before = _porcelain(rapid7_root)
        customer_before = _porcelain(customer_repo)
        exit_code, payload = _start("audit", customer_repo, "--dry-run")
        assert exit_code == EXIT_OK
        assert _porcelain(rapid7_root) == rapid7_before == ""
        assert _porcelain(customer_repo) == customer_before == ""
        # no worktree container appeared for a read mode
        assert not (customer_repo.parent / f"{customer_repo.name}.saena-worktrees").exists()
        # nothing customer-derived landed under the RAPID-7 root
        run_dir = Path(payload["report_paths"][0]).parent
        assert rapid7_root not in run_dir.parents

    def test_implement_dry_run_writes_nothing_customer_side(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path, complete_intake: Path
    ) -> None:
        exit_code, payload = _start(
            "implement", customer_repo, "--dry-run", "--intake", str(complete_intake)
        )
        assert exit_code == EXIT_OK
        assert not (customer_repo.parent / f"{customer_repo.name}.saena-worktrees").exists()
        assert _porcelain(customer_repo) == ""
        # rendered argv still targets the (future) worktree path
        assert ".saena-worktrees" in payload["launch"]["argv"][2]


class TestImplement:
    def test_implement_creates_worktree_and_records_repo_edit(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path, complete_intake: Path
    ) -> None:
        launches: list[tuple[str, ...]] = []

        def runner(argv, cwd, env):  # type: ignore[no-untyped-def]
            launches.append(tuple(argv))
            return 0

        exit_code, payload = _start(
            "implement",
            customer_repo,
            "--intake",
            str(complete_intake),
            launch_runner=runner,
        )
        assert exit_code == EXIT_OK
        run_id = payload["run_id"]
        worktree = customer_repo.parent / f"{customer_repo.name}.saena-worktrees" / run_id
        assert worktree.is_dir()
        branch = run_git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        assert branch == f"saena-pilot/{run_id}"
        # the launch attached the WORKTREE, not the customer root
        assert launches == [("claude", "--add-dir", str(worktree))]
        # evidence recorded the worktree creation as a repo-edit event
        events = [
            json.loads(line)
            for line in (pilot_home / "pilot-runs" / run_id / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        repo_edits = [e for e in events if e["kind"] == "repo-edit"]
        assert [e["event"] for e in repo_edits] == ["worktree-created"]
        # the customer ROOT tree itself stays clean
        assert _porcelain(customer_repo) == ""


class TestVerifyStatusResume:
    def _audit_run(self, customer_repo: Path) -> str:
        exit_code, payload = _start("audit", customer_repo, "--dry-run")
        assert exit_code == EXIT_OK
        return str(payload["run_id"])

    def test_verify_green_then_red_after_tamper(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._audit_run(customer_repo)
        assert main(["--mode", "verify", "--run-id", run_id]) == EXIT_OK
        assert "VERIFIED" in capsys.readouterr().out

        events = pilot_home / "pilot-runs" / run_id / "events.jsonl"
        lines = events.read_text(encoding="utf-8").splitlines(keepends=True)
        events.write_text("".join(lines[:-1]), encoding="utf-8")  # truncate
        assert main(["--mode", "verify", "--run-id", run_id]) == EXIT_VALIDATION_FAILED
        assert "truncation" in capsys.readouterr().err

    def test_status_lists_and_details_runs(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(["--mode", "status"]) == EXIT_OK
        assert "no pilot runs" in capsys.readouterr().out
        run_id = self._audit_run(customer_repo)
        assert main(["--mode", "status", "--json"]) == EXIT_OK
        assert json.loads(capsys.readouterr().out) == {"runs": [run_id]}
        assert main(["--mode", "status", "--run-id", run_id, "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["evidence_status"] == "VERIFIED"
        assert payload["customer_repo"] == str(customer_repo.resolve())

    def test_resume_ok_when_world_unchanged(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._audit_run(customer_repo)
        assert main(["--mode", "resume", "--run-id", run_id]) == EXIT_OK
        assert "RESUMABLE" in capsys.readouterr().out
        # resume itself appended a chain-valid evidence record
        assert main(["--mode", "verify", "--run-id", run_id]) == EXIT_OK
        capsys.readouterr()

    def test_resume_refused_after_customer_moves(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._audit_run(customer_repo)
        (customer_repo / "drift.txt").write_text("x", encoding="utf-8")
        assert run_git(customer_repo, "add", "-A").returncode == 0
        assert run_git(customer_repo, "commit", "-q", "-m", "drift").returncode == 0
        assert main(["--mode", "resume", "--run-id", run_id]) == EXIT_VALIDATION_FAILED
        err = capsys.readouterr().err
        assert "refusing to resume" in err and "customer HEAD" in err

    def test_resume_refused_after_manifest_change(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._audit_run(customer_repo)
        manifest = rapid7_root / ".claude" / "skills" / "manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["bundle_name"] = "tampered-bundle"
        manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        # NB: rapid7 HEAD unchanged (working-tree-only edit) — the manifest
        # hash comparison must catch this on its own.
        assert main(["--mode", "resume", "--run-id", run_id]) == EXIT_VALIDATION_FAILED
        assert "manifest changed" in capsys.readouterr().err

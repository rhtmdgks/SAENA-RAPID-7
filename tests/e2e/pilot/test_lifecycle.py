"""E2E: no-copy invariant, implement worktree isolation, evidence integrity,
and bundle fail-closed — all against the REAL RAPID-7 root and its real skill
bundle, with SYNTHETIC customer repos in tmp_path.

Scenario keys exercised: ``no_copy_invariant``, ``implement_worktree_isolation``,
``evidence_integrity``, ``bundle_fail_closed``.
"""

from __future__ import annotations

import json
from pathlib import Path

from _e2e_run import (
    assert_settings_intact,
    event_names,
    op,
    read_events,
    start,
)
from saena_pilot.cli import (
    EXIT_BUNDLE_INVALID,
    EXIT_OK,
    EXIT_VALIDATION_FAILED,
)
from saena_pilot.models import canonical_json


class _Recorder:
    """Injectable launch runner that records argv/cwd and never launches."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def __call__(self, argv, cwd, env) -> int:  # type: ignore[no-untyped-def]
        self.calls.append((tuple(argv), str(cwd)))
        return 0


_TRANSIENT_ARTIFACTS = (
    "coverage.xml",
    ".coverage",
    ".pytest_cache",
    "__pycache__",
    ".devcontainer/devcontainer-lock.json",
)


def _filter_transient(porcelain: str) -> str:
    """Drop lines for test-harness build artifacts (coverage data files, caches,
    the pre-existing untracked devcontainer lockfile) the full `just verify` run
    creates at the repo root — not customer copies, else the before/after RAPID-7
    delta is spuriously non-empty."""
    kept = []
    for line in porcelain.splitlines():
        path = line[3:] if len(line) > 3 else line
        if any(marker in path for marker in _TRANSIENT_ARTIFACTS):
            continue
        kept.append(line)
    return "\n".join(kept)


def _rapid7_porcelain(builders, root: Path) -> str:  # noqa: ANN001
    result = builders.run_git(root, "status", "--porcelain")
    assert result.returncode == 0
    return _filter_transient(result.stdout)


# --------------------------------------------------------------------------- #
# no-copy-invariant
# --------------------------------------------------------------------------- #
def test_no_copy_invariant__audit_leaves_both_repos_unchanged(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    rapid7_before = _rapid7_porcelain(build, real_rapid7_root)
    customer_before = build.porcelain(customer)

    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK

    # The pilot added NOTHING to either tree (porcelain identical, customer clean).
    assert _rapid7_porcelain(build, real_rapid7_root) == rapid7_before
    assert build.porcelain(customer) == customer_before == ""
    # No customer-derived path appears in RAPID-7's status.
    assert customer.name not in _rapid7_porcelain(build, real_rapid7_root)
    # No worktree container appeared for a read mode.
    assert not (customer.parent / f"{customer.name}.saena-worktrees").exists()


def test_no_copy_invariant__run_metadata_only_under_pilot_home(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    run_id = res.json["run_id"]

    run_dir = pilot_home / "pilot-runs" / run_id
    assert run_dir.is_dir()
    for name in ("run.json", "contract.json", "events.jsonl", "report-audit.json"):
        assert (run_dir / name).is_file()
    # Every recorded report path is under pilot_home, never under either repo.
    for p in res.json["report_paths"]:
        rp = Path(p).resolve()
        assert pilot_home.resolve() in rp.parents
        assert real_rapid7_root not in rp.parents
        assert customer not in rp.parents


def test_no_copy_invariant__implement_does_not_copy_customer_into_rapid7(
    real_rapid7_root, pilot_home, customers, build, complete_intake
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    rapid7_before = _rapid7_porcelain(build, real_rapid7_root)
    rec = _Recorder()
    res = start("implement", customer, "--intake", str(complete_intake), launch_runner=rec)
    assert res.exit_code == EXIT_OK
    # RAPID-7 tree is byte-for-byte unchanged; no customer content landed in it.
    assert _rapid7_porcelain(build, real_rapid7_root) == rapid7_before
    assert customer.name not in _rapid7_porcelain(build, real_rapid7_root)


# --------------------------------------------------------------------------- #
# implement-worktree-isolation
# --------------------------------------------------------------------------- #
def test_implement_worktree_isolation__creates_dedicated_worktree_branch(
    real_rapid7_root, pilot_home, customers, build, complete_intake
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    rec = _Recorder()
    res = start("implement", customer, "--intake", str(complete_intake), launch_runner=rec)
    assert res.exit_code == EXIT_OK
    run_id = res.json["run_id"]

    worktree = customer.parent / f"{customer.name}.saena-worktrees" / run_id
    assert worktree.is_dir()
    branch = build.run_git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert branch == f"saena-pilot/{run_id}"
    # evidence recorded the worktree creation as a repo-edit event
    repo_edits = [e for e in read_events(pilot_home, run_id) if e["kind"] == "repo-edit"]
    assert [e["event"] for e in repo_edits] == ["worktree-created"]


def test_implement_worktree_isolation__launch_attaches_worktree_not_root(
    real_rapid7_root, pilot_home, customers, build, complete_intake
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    rec = _Recorder()
    res = start("implement", customer, "--intake", str(complete_intake), launch_runner=rec)
    assert res.exit_code == EXIT_OK
    run_id = res.json["run_id"]
    worktree = customer.parent / f"{customer.name}.saena-worktrees" / run_id
    # The launch attached the WORKTREE, not the customer root; cwd stayed RAPID-7.
    assert rec.calls == [(("claude", "--add-dir", str(worktree)), str(real_rapid7_root))]
    assert_settings_intact(res.json["launch"], real_rapid7_root)
    assert res.json["launch"]["argv"][2] == str(worktree)


def test_implement_worktree_isolation__customer_root_stays_clean(
    real_rapid7_root, pilot_home, customers, build, complete_intake
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    rec = _Recorder()
    res = start("implement", customer, "--intake", str(complete_intake), launch_runner=rec)
    assert res.exit_code == EXIT_OK
    # The customer ROOT working tree is untouched (writes go to the worktree).
    assert build.porcelain(customer) == ""


def test_implement_worktree_isolation__worktree_outside_both_repos(
    real_rapid7_root, pilot_home, customers, build, complete_intake
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    rec = _Recorder()
    res = start("implement", customer, "--intake", str(complete_intake), launch_runner=rec)
    assert res.exit_code == EXIT_OK
    run_id = res.json["run_id"]
    worktree = (customer.parent / f"{customer.name}.saena-worktrees" / run_id).resolve()
    # The worktree is a SIBLING of the customer root — inside neither repo.
    assert real_rapid7_root.resolve() not in worktree.parents
    assert customer.resolve() not in worktree.parents


def test_implement_worktree_isolation__full_sequence_shares_run_id(
    real_rapid7_root, pilot_home, customers, build, complete_intake
) -> None:  # noqa: ANN001
    """implement → verify → status → resume all share ONE run id."""
    customer = build.build_nextjs_repo(customers)
    rec = _Recorder()
    res = start("implement", customer, "--intake", str(complete_intake), launch_runner=rec)
    assert res.exit_code == EXIT_OK
    run_id = res.json["run_id"]

    assert op("verify", run_id).exit_code == EXIT_OK
    status = op("status", run_id)
    assert status.exit_code == EXIT_OK
    assert status.json["mode_history"][0]["mode"] == "implement"
    assert status.json["evidence_status"] == "VERIFIED"
    assert status.json["worktree_path"].endswith(run_id)
    resume = op("resume", run_id)
    assert resume.exit_code == EXIT_OK
    assert resume.json["resumable"] is True
    assert resume.json["last_mode"] == "implement"


# --------------------------------------------------------------------------- #
# evidence-integrity
# --------------------------------------------------------------------------- #
def test_evidence_integrity__genesis_binds_skill_bundle(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    run_id = res.json["run_id"]

    genesis = read_events(pilot_home, run_id)[0]
    assert genesis["event"] == "run-bound"
    payload = genesis["payload"]
    # The genesis record BINDS the validated skill bundle fingerprint.
    assert payload["manifest_sha256"]
    assert payload["manifest_schema_version"] == "saena.skill-manifest/v1"
    assert len(payload["skill_names"]) == 16
    # …and the same manifest sha is what the audit report bound.
    assert res.json["report"]["bundle"]["manifest_sha256"] == payload["manifest_sha256"]


def test_evidence_integrity__records_lifecycle_events_in_order(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_OK
    run_id = res.json["run_id"]
    names = event_names(pilot_home, run_id)
    # The real modes/events, in order, for a read-mode start.
    assert names[0] == "run-bound"
    assert names[1] == "boundary-validated"
    assert names[2] == "bundle-validated"
    assert names[3] == "contract-recorded"
    assert "report-written" in names
    assert "launch-rendered" in names
    # order: report-written precedes launch-rendered
    assert names.index("report-written") < names.index("launch-rendered")


def test_evidence_integrity__verify_green_then_red_after_tamper(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    res = start("audit", customer, "--dry-run")
    run_id = res.json["run_id"]
    assert op("verify", run_id).exit_code == EXIT_OK

    events = pilot_home / "pilot-runs" / run_id / "events.jsonl"
    lines = events.read_text(encoding="utf-8").splitlines()
    # Mutate a genesis payload VALUE (re-serialized canonically, but the stored
    # payload_hash no longer matches the tampered payload).
    genesis = json.loads(lines[0])
    genesis["payload"]["domain"] = "https://tampered.example"
    lines[0] = canonical_json(genesis)
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")
    bad = op("verify", run_id)
    assert bad.exit_code == EXIT_VALIDATION_FAILED
    assert "evidence" in bad.err.lower() or "mutat" in bad.err.lower()


def test_evidence_integrity__truncation_detected(
    real_rapid7_root, pilot_home, customers, build
) -> None:  # noqa: ANN001
    customer = build.build_nextjs_repo(customers)
    run_id = start("audit", customer, "--dry-run").json["run_id"]
    assert op("verify", run_id).exit_code == EXIT_OK
    events = pilot_home / "pilot-runs" / run_id / "events.jsonl"
    lines = events.read_text(encoding="utf-8").splitlines(keepends=True)
    events.write_text("".join(lines[:-1]), encoding="utf-8")  # drop the last record
    bad = op("verify", run_id)
    assert bad.exit_code == EXIT_VALIDATION_FAILED
    assert "truncation" in bad.err.lower() or "head" in bad.err.lower()


# --------------------------------------------------------------------------- #
# bundle-fail-closed
# --------------------------------------------------------------------------- #
def test_bundle_fail_closed__missing_manifest_refuses_start(
    monkeypatch, pilot_home, customers, build, tmp_path
) -> None:  # noqa: ANN001
    fake_root = build.build_broken_rapid7_root(tmp_path / "roots", bundle="missing")
    customer = build.build_nextjs_repo(customers)
    monkeypatch.chdir(fake_root)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_BUNDLE_INVALID
    assert "manifest" in res.err.lower()


def test_bundle_fail_closed__empty_skill_bundle_refuses_start(
    monkeypatch, pilot_home, customers, build, tmp_path
) -> None:  # noqa: ANN001
    fake_root = build.build_broken_rapid7_root(tmp_path / "roots", bundle="empty_skills")
    customer = build.build_nextjs_repo(customers)
    monkeypatch.chdir(fake_root)
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_BUNDLE_INVALID
    assert "skill" in res.err.lower() or "bundle" in res.err.lower()


def test_bundle_fail_closed__no_bypass_env_or_flag(
    monkeypatch, pilot_home, customers, build, tmp_path
) -> None:  # noqa: ANN001
    """There is no env var or flag that bypasses the bundle gate — even an
    invented one leaves the failure intact (argparse rejects unknown flags)."""
    fake_root = build.build_broken_rapid7_root(tmp_path / "roots", bundle="missing")
    customer = build.build_nextjs_repo(customers)
    monkeypatch.chdir(fake_root)
    monkeypatch.setenv("SAENA_PILOT_SKIP_BUNDLE", "1")  # not consulted by any code path
    res = start("audit", customer, "--dry-run")
    assert res.exit_code == EXIT_BUNDLE_INVALID
    # A made-up bypass FLAG is an argparse usage error (exit 2), never a bypass.
    usage = start("audit", customer, "--dry-run", "--skip-bundle")
    assert usage.exit_code == 2

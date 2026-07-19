"""Run store — location, roundtrip, resume mismatch refusal."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
from _pilot_fixtures import head_sha, make_git_repo, run_git
from saena_pilot import runstore
from saena_pilot.errors import ResumeMismatchError, ValidationFailedError
from saena_pilot.evidence import ChainHead


def _create(rapid7_root: Path, customer_repo: Path) -> runstore.RunRecord:
    return runstore.create_run(
        customer_repo=customer_repo,
        domain="https://customer.example",
        customer_id="tenant-1",
        rapid7_sha=head_sha(rapid7_root),
        customer_sha=head_sha(customer_repo),
        contract_sha256="d" * 64,
        manifest_sha256="e" * 64,
        mode="audit",
    )


class TestLocation:
    def test_env_override_honored(self, pilot_home: Path) -> None:
        assert runstore.pilot_home() == pilot_home
        assert runstore.runs_root() == pilot_home / "pilot-runs"

    def test_default_is_home_dot_saena(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAENA_PILOT_HOME", raising=False)
        assert runstore.pilot_home() == Path.home() / ".saena"

    def test_store_inside_rapid7_refused(
        self, rapid7_root: Path, customer_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAENA_PILOT_HOME", str(rapid7_root / ".saena"))
        with pytest.raises(ValidationFailedError, match="must never live in either repo"):
            runstore.ensure_store_outside_repos(rapid7_root, customer_repo)

    def test_store_inside_customer_refused(
        self, rapid7_root: Path, customer_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAENA_PILOT_HOME", str(customer_repo / "meta"))
        with pytest.raises(ValidationFailedError):
            runstore.ensure_store_outside_repos(rapid7_root, customer_repo)

    def test_store_outside_both_accepted(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        root = runstore.ensure_store_outside_repos(rapid7_root, customer_repo)
        assert root == Path(pilot_home / "pilot-runs").resolve()


class TestRoundtrip:
    def test_create_load_roundtrip(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        record = _create(rapid7_root, customer_repo)
        uuid.UUID(record.run_id)  # run id is a UUID4-shaped id
        loaded = runstore.load_run(record.run_id)
        assert loaded.to_dict() == record.to_dict()
        assert runstore.list_runs() == [record.run_id]

    def test_missing_run_rejected(self, pilot_home: Path) -> None:
        with pytest.raises(ValidationFailedError, match="not found"):
            runstore.load_run("no-such-run")

    def test_unknown_keys_in_run_json_rejected(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        record = _create(rapid7_root, customer_repo)
        path = runstore.run_dir(record.run_id) / "run.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["sneaky"] = True
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValidationFailedError, match="unknown keys"):
            runstore.load_run(record.run_id)

    def test_evidence_head_mirrored(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        record = _create(rapid7_root, customer_repo)
        runstore.record_evidence_head(record, ChainHead(count=3, chain_hash="f" * 64))
        loaded = runstore.load_run(record.run_id)
        assert loaded.chain_head == ChainHead(count=3, chain_hash="f" * 64)


class TestResumeValidation:
    def test_matching_world_passes(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        record = _create(rapid7_root, customer_repo)
        runstore.validate_resume(record, rapid7_root=rapid7_root)  # no raise

    def test_rapid7_sha_mismatch_refused_with_explicit_report(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        record = _create(rapid7_root, customer_repo)
        (rapid7_root / "new.txt").write_text("x", encoding="utf-8")
        assert run_git(rapid7_root, "add", "-A").returncode == 0
        assert run_git(rapid7_root, "commit", "-q", "-m", "advance").returncode == 0
        with pytest.raises(ResumeMismatchError) as excinfo:
            runstore.validate_resume(record, rapid7_root=rapid7_root)
        message = str(excinfo.value)
        assert "RAPID-7 HEAD" in message
        assert record.rapid7_sha in message  # expected vs actual, explicitly

    def test_customer_sha_mismatch_refused(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        record = _create(rapid7_root, customer_repo)
        (customer_repo / "new.txt").write_text("x", encoding="utf-8")
        assert run_git(customer_repo, "add", "-A").returncode == 0
        assert run_git(customer_repo, "commit", "-q", "-m", "advance").returncode == 0
        with pytest.raises(ResumeMismatchError, match="customer HEAD"):
            runstore.validate_resume(record, rapid7_root=rapid7_root)

    def test_vanished_customer_repo_refused(
        self, rapid7_root: Path, tmp_path: Path, pilot_home: Path
    ) -> None:
        doomed = make_git_repo(tmp_path / "doomed")
        record = _create(rapid7_root, doomed)
        shutil.rmtree(doomed)
        with pytest.raises(ResumeMismatchError):
            runstore.validate_resume(record, rapid7_root=rapid7_root)

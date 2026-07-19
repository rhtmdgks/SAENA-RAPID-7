"""Edge-path coverage: CLI error mapping, evidence verify branches,
module entry points, and remaining fail-closed corners."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest
from _pilot_fixtures import make_git_repo, run_git
from saena_pilot import cli
from saena_pilot.bundle import enforce_bundle
from saena_pilot.cli import (
    EXIT_OK,
    EXIT_RUNTIME_ERROR,
    EXIT_VALIDATION_FAILED,
    main,
)
from saena_pilot.errors import (
    BundleInvalidError,
    EvidenceIntegrityError,
    PilotError,
    ValidationFailedError,
    WorktreeCollisionError,
)
from saena_pilot.evidence import EventKind, EvidenceLog, verify_chain
from saena_pilot.intake import build_contract
from saena_pilot.models import Mode, canonical_json, sha256_text
from saena_pilot.runstore import RunRecord, load_run, run_dir, runs_root
from saena_pilot.worktree import create_customer_worktree

DOMAIN = "https://customer.example"

BINDING: dict[str, Any] = {
    "rapid7_sha": "a" * 40,
    "customer_sha": "b" * 40,
    "domain": DOMAIN,
    "mode": "audit",
    "run_id": "11111111-2222-3333-4444-555555555555",
    "manifest_schema_version": "saena.skill-manifest/v1",
    "manifest_sha256": "c" * 64,
    "skill_names": ["saena-intake"],
}


def _audit(customer_repo: Path, *extra: str) -> list[str]:
    return ["--customer-repo", str(customer_repo), "--domain", DOMAIN, "--mode", "audit", *extra]


class TestCliErrorMapping:
    def test_git_root_without_claude_marker_rejected(
        self,
        tmp_path: Path,
        customer_repo: Path,
        pilot_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        bare = make_git_repo(tmp_path / "bare-repo")
        monkeypatch.chdir(bare)
        assert main(_audit(customer_repo, "--dry-run")) == EXIT_VALIDATION_FAILED
        assert "does not look like the SAENA RAPID-7 root" in capsys.readouterr().err

    def test_rapid7_without_head_rejected(
        self,
        tmp_path: Path,
        customer_repo: Path,
        pilot_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = tmp_path / "headless"
        root.mkdir()
        assert run_git(root, "init", "-q").returncode == 0
        (root / ".claude").mkdir()
        monkeypatch.chdir(root)
        assert main(_audit(customer_repo, "--dry-run")) == EXIT_VALIDATION_FAILED
        assert "no resolvable HEAD" in capsys.readouterr().err

    def test_unexpected_exception_maps_to_runtime_error(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def boom(domain: str) -> str:
            raise RuntimeError("wire tripped")

        monkeypatch.setattr(cli, "validate_domain", boom)
        assert main(_audit(customer_repo, "--dry-run")) == EXIT_RUNTIME_ERROR
        assert "unexpected error: RuntimeError" in capsys.readouterr().err

    def test_bare_pilot_error_maps_to_runtime_error(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def boom(domain: str) -> str:
            raise PilotError("uncategorized failure")

        monkeypatch.setattr(cli, "validate_domain", boom)
        assert main(_audit(customer_repo, "--dry-run")) == EXIT_RUNTIME_ERROR
        capsys.readouterr()

    def test_entry_exits_with_main_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["saena-pilot", "--version"])
        with pytest.raises(SystemExit) as excinfo:
            cli.entry()
        assert excinfo.value.code == EXIT_OK

    def test_python_dash_m_module_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["saena-pilot", "--help"])
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module("saena_pilot", run_name="__main__")
        assert excinfo.value.code == EXIT_OK


class TestCliHumanOutputs:
    def _run_audit(self, customer_repo: Path, capsys: pytest.CaptureFixture[str]) -> str:
        assert main(_audit(customer_repo, "--dry-run", "--json")) == EXIT_OK
        return str(json.loads(capsys.readouterr().out)["run_id"])

    def test_verify_json_output(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._run_audit(customer_repo, capsys)
        assert main(["--mode", "verify", "--run-id", run_id, "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["verified"] is True and payload["run_id"] == run_id

    def test_status_human_listing_and_detail(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._run_audit(customer_repo, capsys)
        assert main(["--mode", "status"]) == EXIT_OK
        assert run_id in capsys.readouterr().out
        assert main(["--mode", "status", "--run-id", run_id]) == EXIT_OK
        out = capsys.readouterr().out
        assert "customer repo:" in out and "evidence:      VERIFIED" in out

    def test_status_reports_invalid_evidence_without_failing(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._run_audit(customer_repo, capsys)
        events = runs_root() / run_id / "events.jsonl"
        events.write_text("", encoding="utf-8")
        assert main(["--mode", "status", "--run-id", run_id]) == EXIT_OK
        assert "INVALID" in capsys.readouterr().out

    def test_preflight_suggests_actions_for_detached_and_nested(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        make_git_repo(customer_repo / "vendor" / "inner")
        assert run_git(customer_repo, "checkout", "-q", "--detach").returncode == 0
        argv = [
            "--customer-repo",
            str(customer_repo),
            "--domain",
            DOMAIN,
            "--mode",
            "preflight",
            "--json",
        ]
        assert main(argv) == EXIT_OK
        actions = json.loads(capsys.readouterr().out)["report"]["suggested_human_actions"]
        assert any("named branch" in a for a in actions)
        assert any("nested git repositories" in a for a in actions)

    def test_resume_json_output(
        self,
        rapid7_root: Path,
        customer_repo: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._run_audit(customer_repo, capsys)
        assert main(["--mode", "resume", "--run-id", run_id, "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["resumable"] is True and payload["last_mode"] == "audit"


def _reforge(path: Path, index: int, mutate: Any) -> None:
    """Mutate record `index` then recompute payload/chain hashes for the
    whole file — a maximal forgery that leaves only semantic checks to fire."""
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    mutate(records[index])
    prev = "0" * 64
    lines = []
    for record in records:
        record["payload_hash"] = sha256_text(canonical_json(record["payload"]))
        record.pop("chain_hash", None)
        record["prev_chain_hash"] = prev
        record["chain_hash"] = sha256_text(prev + canonical_json(record))
        prev = record["chain_hash"]
        lines.append(canonical_json(record) + "\n")
    path.write_text("".join(lines), encoding="utf-8")


class TestEvidenceSemanticForgeries:
    @pytest.fixture
    def log(self, tmp_path: Path) -> EvidenceLog:
        log = EvidenceLog.create(tmp_path / "events.jsonl", dict(BINDING))
        log.append("boundary-validated", EventKind.RUN_META, {"ok": True})
        return log

    def test_reforged_wrong_schema_version_detected(self, log: EvidenceLog) -> None:
        _reforge(log.path, 1, lambda r: r.update(schema_version="saena.pilot-evidence/v0"))
        with pytest.raises(EvidenceIntegrityError, match="schema_version"):
            verify_chain(log.path)

    def test_reforged_unknown_kind_detected(self, log: EvidenceLog) -> None:
        _reforge(log.path, 1, lambda r: r.update(kind="invented-kind"))
        with pytest.raises(EvidenceIntegrityError, match="unknown event kind"):
            verify_chain(log.path)

    def test_reforged_genesis_event_rename_detected(self, log: EvidenceLog) -> None:
        _reforge(log.path, 0, lambda r: r.update(event="not-run-bound"))
        with pytest.raises(EvidenceIntegrityError, match="genesis"):
            verify_chain(log.path)

    def test_reforged_genesis_binding_strip_detected(self, log: EvidenceLog) -> None:
        _reforge(log.path, 0, lambda r: r["payload"].pop("customer_sha"))
        with pytest.raises(EvidenceIntegrityError, match="binding missing"):
            verify_chain(log.path)

    def test_reforged_non_object_payload_detected(self, log: EvidenceLog) -> None:
        _reforge(log.path, 1, lambda r: r.update(payload="scalar"))
        with pytest.raises(EvidenceIntegrityError, match="payload"):
            verify_chain(log.path)

    def test_non_object_record_line_detected(self, log: EvidenceLog) -> None:
        with log.path.open("a", encoding="utf-8") as handle:
            handle.write("[1, 2, 3]\n")
        with pytest.raises(EvidenceIntegrityError, match="not an object"):
            verify_chain(log.path)

    def test_corrupt_tail_blocks_append(self, log: EvidenceLog) -> None:
        with log.path.open("a", encoding="utf-8") as handle:
            handle.write("{garbage\n")
        with pytest.raises(EvidenceIntegrityError, match="tail unreadable"):
            log.append("x", EventKind.RUN_META, {})

    def test_non_string_tail_chain_hash_blocks_append(self, log: EvidenceLog) -> None:
        records = [
            json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines() if line
        ]
        records[-1]["chain_hash"] = 12345
        log.path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        with pytest.raises(EvidenceIntegrityError, match="non-string chain hash"):
            log.append("x", EventKind.RUN_META, {})

    def test_head_of_empty_log_fails(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(EvidenceIntegrityError, match="empty"):
            EvidenceLog(empty).head()


class TestRemainingFailClosedCorners:
    def test_bundle_rejects_unnamed_skill_entry(self, rapid7_root: Path) -> None:
        manifest_path = rapid7_root / ".claude" / "skills" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["skills"] = [{"version": "0.1.0"}]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(BundleInvalidError, match="without a name"):
            enforce_bundle(rapid7_root)

    def test_bundle_rejects_missing_bundle_name(self, rapid7_root: Path) -> None:
        manifest_path = rapid7_root / ".claude" / "skills" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["bundle_name"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(BundleInvalidError, match="bundle_name"):
            enforce_bundle(rapid7_root)

    def test_intake_rejects_non_string_list_values(self) -> None:
        with pytest.raises(ValidationFailedError, match="list of strings"):
            build_contract(
                customer_repo="/tmp/x",
                domain=DOMAIN,
                customer_id=None,
                intake_data={"allowed_write_scope": [1, 2]},
            )

    def test_intake_rejects_empty_customer_id(self) -> None:
        with pytest.raises(ValidationFailedError, match="non-empty"):
            build_contract(
                customer_repo="/tmp/x", domain=DOMAIN, customer_id="  ", intake_data=None
            )

    def test_intake_rejects_non_string_classification(self) -> None:
        with pytest.raises(ValidationFailedError, match="data_classification"):
            build_contract(
                customer_repo="/tmp/x",
                domain=DOMAIN,
                customer_id=None,
                intake_data={"data_classification": 42},
            )

    def test_domain_unparsable_url_rejected(self) -> None:
        with pytest.raises(ValidationFailedError, match="unparsable"):
            cli.validate_domain("https://[::1")

    def test_worktree_git_failure_surfaces_as_collision_error(self, customer_repo: Path) -> None:
        # ".." is illegal in a git ref name → `git worktree add -b` fails and
        # must surface as the distinct collision/failure error, never force.
        with pytest.raises(WorktreeCollisionError, match="worktree add failed"):
            create_customer_worktree(customer_repo, "bad..run", mode=Mode.IMPLEMENT)

    def test_run_record_missing_keys_rejected(self) -> None:
        with pytest.raises(ValidationFailedError, match="missing keys"):
            RunRecord.from_dict({"schema_version": "saena.pilot-run/v1"}, source="test")

    def test_run_record_wrong_schema_rejected(
        self, rapid7_root: Path, customer_repo: Path, pilot_home: Path
    ) -> None:
        record = RunRecord(
            run_id="r1",
            created_ts="t",
            customer_repo=str(customer_repo),
            domain=DOMAIN,
            customer_id=None,
            rapid7_sha="a" * 40,
            customer_sha="b" * 40,
            contract_sha256="c" * 64,
            manifest_sha256="d" * 64,
        )
        data = record.to_dict()
        data["schema_version"] = "saena.pilot-run/v0"
        with pytest.raises(ValidationFailedError, match="schema_version"):
            RunRecord.from_dict(data, source="test")

    def test_run_json_non_object_rejected(self, pilot_home: Path) -> None:
        directory = run_dir("weird-run")
        directory.mkdir(parents=True)
        (directory / "run.json").write_text("[1]", encoding="utf-8")
        with pytest.raises(ValidationFailedError, match="JSON object"):
            load_run("weird-run")

    def test_chain_head_none_before_first_append(self) -> None:
        record = RunRecord(
            run_id="r1",
            created_ts="t",
            customer_repo="/x",
            domain=DOMAIN,
            customer_id=None,
            rapid7_sha="a" * 40,
            customer_sha="b" * 40,
            contract_sha256="c" * 64,
            manifest_sha256="d" * 64,
        )
        assert record.chain_head is None

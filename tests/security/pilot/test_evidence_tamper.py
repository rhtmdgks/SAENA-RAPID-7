"""Attack 9 — evidence replay / tamper.

The evidence chain is tamper-evident: `verify_chain` re-walks the file and
fails on any mutation, truncation, splice, reorder, or seq gap. A clean chain
verifies. Every mutating case asserts `EvidenceIntegrityError`; the clean case
asserts a returned `ChainHead`; the CLI `verify` mode maps a clean chain to
`EXIT_OK` and a tampered chain to `EXIT_VALIDATION_FAILED`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _sec_fixtures import make_git_repo
from saena_pilot.cli import EXIT_OK, EXIT_VALIDATION_FAILED, main
from saena_pilot.errors import EvidenceIntegrityError
from saena_pilot.evidence import ChainHead, EventKind, EvidenceLog, verify_chain

DOMAIN = "https://customer.example"


def _binding() -> dict[str, object]:
    return {
        "rapid7_sha": "a" * 40,
        "customer_sha": "b" * 40,
        "domain": DOMAIN,
        "mode": "audit",
        "run_id": "run-x",
        "manifest_schema_version": "saena.skill-manifest/v1",
        "manifest_sha256": "c" * 64,
        "skill_names": ["saena-intake"],
    }


def _seed_chain(path: Path, records: int = 3) -> ChainHead:
    log = EvidenceLog.create(path, _binding())
    for i in range(records):
        log.append(f"event-{i}", EventKind.RUN_META, {"i": i})
    return log.head()


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


class TestCleanChainVerifies:
    def test_clean_chain_verifies(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        head = _seed_chain(path)
        result = verify_chain(path, expected_head=head)
        assert result == head
        assert result.count == 4  # genesis + 3

    def test_clean_chain_verifies_without_expected_head(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        _seed_chain(path)
        assert verify_chain(path).count == 4


class TestTamperDetected:
    def test_mutated_payload_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        _seed_chain(path)
        lines = _lines(path)
        rec = json.loads(lines[2])
        rec["payload"] = {"i": 999}  # payload_hash no longer matches
        lines[2] = json.dumps(rec, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(path)

    def test_mutated_field_without_rehash_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        _seed_chain(path)
        lines = _lines(path)
        rec = json.loads(lines[1])
        rec["event"] = "tampered-event"  # chain_hash no longer matches
        lines[1] = json.dumps(rec, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(path)

    def test_truncated_chain_fails_against_expected_head(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        head = _seed_chain(path)
        lines = _lines(path)
        path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")  # drop last record
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(path, expected_head=head)

    def test_reordered_records_fail(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        _seed_chain(path)
        lines = _lines(path)
        lines[1], lines[2] = lines[2], lines[1]  # swap two mid records
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(path)

    def test_spliced_record_from_another_run_fails(self, tmp_path: Path) -> None:
        path_a = tmp_path / "a.jsonl"
        path_b = tmp_path / "b.jsonl"
        _seed_chain(path_a)
        _seed_chain(path_b)
        a_lines = _lines(path_a)
        b_lines = _lines(path_b)
        a_lines[2] = b_lines[2]  # splice a record from run B into run A
        path_a.write_text("\n".join(a_lines) + "\n", encoding="utf-8")
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(path_a)

    def test_dropped_genesis_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        _seed_chain(path)
        lines = _lines(path)
        path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")  # remove genesis
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(path)

    def test_appended_forged_record_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        _seed_chain(path)
        forged = {
            "schema_version": "saena.pilot-evidence/v1",
            "seq": 4,
            "ts": "2026-01-01T00:00:00+00:00",
            "kind": "run-meta",
            "event": "forged",
            "payload": {"x": 1},
            "payload_hash": "0" * 64,
            "prev_chain_hash": "0" * 64,
            "chain_hash": "0" * 64,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(forged, separators=(",", ":")) + "\n")
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(path)

    def test_empty_chain_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(path)

    def test_missing_chain_file_fails(self, tmp_path: Path) -> None:
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(tmp_path / "nope.jsonl")


class TestVerifyModeCliExit:
    def _seed_real_run(
        self,
        rapid7_root: Path,
        tmp_path: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> str:
        from saena_pilot.runstore import list_runs

        customer = make_git_repo(tmp_path / "cust-ev")
        argv = [
            "--customer-repo",
            str(customer),
            "--domain",
            DOMAIN,
            "--mode",
            "audit",
            "--dry-run",
        ]
        assert main(argv) == EXIT_OK
        capsys.readouterr()
        return list_runs()[-1]

    def test_verify_clean_run_exits_ok(
        self,
        rapid7_root: Path,
        tmp_path: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = self._seed_real_run(rapid7_root, tmp_path, pilot_home, capsys)
        assert main(["--mode", "verify", "--run-id", run_id]) == EXIT_OK
        assert "VERIFIED" in capsys.readouterr().out

    def test_verify_tampered_run_exits_validation_failed(
        self,
        rapid7_root: Path,
        tmp_path: Path,
        pilot_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from saena_pilot.runstore import evidence_path

        run_id = self._seed_real_run(rapid7_root, tmp_path, pilot_home, capsys)
        ev = evidence_path(run_id)
        lines = ev.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1])
        rec["payload"] = {"tampered": True}
        lines[1] = json.dumps(rec, separators=(",", ":"))
        ev.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert main(["--mode", "verify", "--run-id", run_id]) == EXIT_VALIDATION_FAILED
        capsys.readouterr()

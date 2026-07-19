"""Evidence chain — append, verify, tamper/truncate/splice detection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from saena_pilot.errors import EvidenceIntegrityError, SecretShapedValueError
from saena_pilot.evidence import (
    BINDING_FIELDS,
    ChainHead,
    EventKind,
    EvidenceLog,
    verify_chain,
)

BINDING: dict[str, Any] = {
    "rapid7_sha": "a" * 40,
    "customer_sha": "b" * 40,
    "domain": "https://customer.example",
    "mode": "audit",
    "run_id": "11111111-2222-3333-4444-555555555555",
    "manifest_schema_version": "saena.skill-manifest/v1",
    "manifest_sha256": "c" * 64,
    "skill_names": ["saena-intake", "ponytail"],
}


@pytest.fixture
def log(tmp_path: Path) -> EvidenceLog:
    log = EvidenceLog.create(tmp_path / "events.jsonl", dict(BINDING))
    log.append("boundary-validated", EventKind.RUN_META, {"ok": True})
    log.append("worktree-created", EventKind.REPO_EDIT, {"worktree": "/tmp/wt"})
    log.append(
        "external-actions-suggested",
        EventKind.EXTERNAL_ACTION_SUGGESTED,
        {"actions": ["ask human to update DNS"]},
    )
    return log


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in records),
        encoding="utf-8",
    )


class TestAppendAndVerify:
    def test_chain_verifies_and_head_matches(self, log: EvidenceLog) -> None:
        head = verify_chain(log.path)
        assert head == log.head()
        assert head.count == 4

    def test_genesis_carries_all_binding_fields(self, log: EvidenceLog) -> None:
        genesis = _records(log.path)[0]
        assert genesis["event"] == "run-bound"
        for field in BINDING_FIELDS:
            assert genesis["payload"][field] == BINDING[field]

    def test_two_event_kinds_distinguished(self, log: EvidenceLog) -> None:
        kinds = [record["kind"] for record in _records(log.path)]
        assert "repo-edit" in kinds
        assert "suggested-external-action" in kinds
        assert kinds.count("repo-edit") == 1

    def test_missing_binding_field_refused_at_create(self, tmp_path: Path) -> None:
        binding = {k: v for k, v in BINDING.items() if k != "customer_sha"}
        with pytest.raises(EvidenceIntegrityError, match="customer_sha"):
            EvidenceLog.create(tmp_path / "e.jsonl", binding)

    def test_create_refuses_existing_file(self, log: EvidenceLog) -> None:
        with pytest.raises(EvidenceIntegrityError, match="already exists"):
            EvidenceLog.create(log.path, dict(BINDING))

    def test_append_requires_existing_log(self, tmp_path: Path) -> None:
        with pytest.raises(EvidenceIntegrityError, match="missing"):
            EvidenceLog(tmp_path / "absent.jsonl").append("x", EventKind.RUN_META, {})

    def test_secret_shaped_payload_refused(self, log: EvidenceLog) -> None:
        with pytest.raises(SecretShapedValueError):
            log.append(
                "oops", EventKind.RUN_META, {"token": "xoxb" + "-1234567890-" + "abcdefghij"}
            )
        # refusal must not have appended anything
        assert verify_chain(log.path).count == 4


class TestTamperDetection:
    def test_payload_mutation_detected(self, log: EvidenceLog) -> None:
        records = _records(log.path)
        records[1]["payload"]["ok"] = False
        _write(log.path, records)
        with pytest.raises(EvidenceIntegrityError, match="payload_hash|chain_hash"):
            verify_chain(log.path)

    def test_recomputed_hash_forgery_detected_by_chain(self, log: EvidenceLog) -> None:
        # Attacker recomputes payload_hash AND chain_hash of record 1 but
        # cannot fix record 2's prev_chain_hash without rewriting the tail —
        # which the recorded head (run.json mirror) then catches.
        head_before = log.head()
        records = _records(log.path)
        del records[2]  # splice a record out
        _write(log.path, records)
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(log.path, expected_head=head_before)

    def test_truncation_detected_via_recorded_head(self, log: EvidenceLog) -> None:
        head_before = log.head()
        records = _records(log.path)
        _write(log.path, records[:-1])
        # internally consistent after truncation...
        verify_chain(log.path)
        # ...but not against the recorded head.
        with pytest.raises(EvidenceIntegrityError, match="truncation"):
            verify_chain(log.path, expected_head=head_before)

    def test_reorder_detected(self, log: EvidenceLog) -> None:
        records = _records(log.path)
        records[1], records[2] = records[2], records[1]
        _write(log.path, records)
        with pytest.raises(EvidenceIntegrityError, match="seq|splice"):
            verify_chain(log.path)

    def test_seq_renumber_splice_detected(self, log: EvidenceLog) -> None:
        records = _records(log.path)
        records[2]["seq"] = 5
        _write(log.path, records)
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(log.path)

    def test_inserted_record_detected(self, log: EvidenceLog) -> None:
        records = _records(log.path)
        forged = dict(records[1])
        records.insert(2, forged)
        _write(log.path, records)
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(log.path)

    def test_unknown_kind_detected(self, log: EvidenceLog) -> None:
        head = log.head()
        records = _records(log.path)
        records[1]["kind"] = "totally-new-kind"
        _write(log.path, records)
        with pytest.raises(EvidenceIntegrityError):
            verify_chain(log.path, expected_head=head)

    def test_empty_and_missing_logs_fail(self, tmp_path: Path) -> None:
        with pytest.raises(EvidenceIntegrityError, match="missing"):
            verify_chain(tmp_path / "absent.jsonl")
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(EvidenceIntegrityError, match="no records"):
            verify_chain(empty)

    def test_expected_head_type(self, log: EvidenceLog) -> None:
        head = log.head()
        assert isinstance(head, ChainHead)
        assert verify_chain(log.path, expected_head=head) == head

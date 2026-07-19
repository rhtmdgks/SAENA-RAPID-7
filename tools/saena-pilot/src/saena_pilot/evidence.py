"""Tamper-evident evidence chain (`saena.pilot-evidence/v1`).

Append-only JSONL. Each record:

    {"schema_version", "seq", "ts", "kind", "event", "payload",
     "payload_hash", "prev_chain_hash", "chain_hash"}

with `payload_hash = sha256(canonical_json(payload))` and
`chain_hash = sha256(prev_chain_hash + canonical_json(record_sans_chain_hash))`.
The genesis record (seq 0, event "run-bound") carries the full run binding:
rapid7_sha, customer_sha, domain, mode, run_id, manifest schema version +
manifest file sha256, and the skill bundle names.

Two customer-relevant event kinds are distinguished by construction:
`repo-edit` (an actual edit inside the customer worktree) vs
`suggested-external-action` (an operational action the pilot merely proposes
to a human — DNS, deploys, robots, CMS). `run-meta` covers pilot lifecycle.

`verify_chain` re-walks the whole file and fails on any mutation, splice,
reorder, or seq gap; truncation is caught by comparing against the head
(count + chain hash) that `runstore` mirrors into `run.json` after every
append.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from saena_pilot.errors import EvidenceIntegrityError
from saena_pilot.models import canonical_json, sha256_text
from saena_pilot.secretguard import guard_tree

EVIDENCE_SCHEMA_VERSION = "saena.pilot-evidence/v1"
GENESIS_PREV_HASH = "0" * 64
GENESIS_EVENT = "run-bound"

#: Binding fields the genesis payload MUST carry (non-empty).
BINDING_FIELDS = (
    "rapid7_sha",
    "customer_sha",
    "domain",
    "mode",
    "run_id",
    "manifest_schema_version",
    "manifest_sha256",
    "skill_names",
)


class EventKind(str, Enum):
    RUN_META = "run-meta"
    REPO_EDIT = "repo-edit"
    EXTERNAL_ACTION_SUGGESTED = "suggested-external-action"


@dataclass(frozen=True, slots=True)
class ChainHead:
    count: int
    chain_hash: str


def _record_chain_hash(prev_chain_hash: str, record_sans_chain: dict[str, Any]) -> str:
    return sha256_text(prev_chain_hash + canonical_json(record_sans_chain))


class EvidenceLog:
    """Append-only accessor for one run's `events.jsonl`."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def create(cls, path: Path, binding: dict[str, Any]) -> EvidenceLog:
        """Create the log with its genesis record binding the run."""
        if path.exists():
            raise EvidenceIntegrityError(
                f"evidence log already exists: {path}",
                context={"path": str(path)},
            )
        missing = [
            field
            for field in BINDING_FIELDS
            if field not in binding or binding[field] in (None, "", [])
        ]
        if missing:
            raise EvidenceIntegrityError(
                f"evidence binding is missing required fields: {missing}",
                context={"missing": missing},
            )
        log = cls(path)
        log._append_record(GENESIS_EVENT, EventKind.RUN_META, binding)
        return log

    def append(self, event: str, kind: EventKind, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.path.exists():
            raise EvidenceIntegrityError(
                f"evidence log missing: {self.path} — cannot append",
                context={"path": str(self.path)},
            )
        return self._append_record(event, kind, payload)

    def _append_record(
        self, event: str, kind: EventKind, payload: dict[str, Any]
    ) -> dict[str, Any]:
        guard_tree(payload, path=f"evidence.{event}")
        seq, prev_hash = self._tail()
        record: dict[str, Any] = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "seq": seq,
            "ts": datetime.now(UTC).isoformat(),
            "kind": kind.value,
            "event": event,
            "payload": payload,
            "payload_hash": sha256_text(canonical_json(payload)),
            "prev_chain_hash": prev_hash,
        }
        record["chain_hash"] = _record_chain_hash(prev_hash, record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(record) + "\n")
        return record

    def _tail(self) -> tuple[int, str]:
        """(next_seq, prev_chain_hash) read from the file itself."""
        if not self.path.exists():
            return 0, GENESIS_PREV_HASH
        last_line: str | None = None
        count = 0
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last_line = line
                    count += 1
        if last_line is None:
            return 0, GENESIS_PREV_HASH
        try:
            last = json.loads(last_line)
            chain_hash = last["chain_hash"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise EvidenceIntegrityError(
                f"evidence log tail unreadable: {self.path}",
                context={"path": str(self.path)},
            ) from exc
        if not isinstance(chain_hash, str):
            raise EvidenceIntegrityError(
                f"evidence log tail has a non-string chain hash: {self.path}",
                context={"path": str(self.path)},
            )
        return count, chain_hash

    def head(self) -> ChainHead:
        count, chain_hash = self._tail()
        if count == 0:
            raise EvidenceIntegrityError(
                f"evidence log is empty: {self.path}",
                context={"path": str(self.path)},
            )
        return ChainHead(count=count, chain_hash=chain_hash)


def verify_chain(path: Path, *, expected_head: ChainHead | None = None) -> ChainHead:
    """Re-walk the full chain; raise `EvidenceIntegrityError` on any
    mutation, splice, reorder, seq gap, malformed record, or (when
    `expected_head` is given, from `run.json`) truncation/substitution."""
    if not path.exists():
        raise EvidenceIntegrityError(f"evidence log missing: {path}", context={"path": str(path)})

    prev_hash = GENESIS_PREV_HASH
    count = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceIntegrityError(
                f"evidence record {line_number} is not valid JSON",
                context={"path": str(path), "line": line_number},
            ) from exc
        if not isinstance(record, dict):
            raise EvidenceIntegrityError(
                f"evidence record {line_number} is not an object",
                context={"path": str(path), "line": line_number},
            )

        def _fail(reason: str, *, line_number: int = line_number) -> EvidenceIntegrityError:
            return EvidenceIntegrityError(
                f"evidence chain invalid at record {line_number}: {reason}",
                context={"path": str(path), "line": line_number, "reason": reason},
            )

        if record.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
            raise _fail("wrong schema_version")
        if record.get("seq") != count:
            raise _fail(f"seq {record.get('seq')!r} != expected {count} (splice/reorder)")
        if record.get("prev_chain_hash") != prev_hash:
            raise _fail("prev_chain_hash does not match previous record (splice)")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise _fail("payload is not an object")
        if record.get("payload_hash") != sha256_text(canonical_json(payload)):
            raise _fail("payload_hash mismatch (payload mutated)")
        claimed_chain_hash = record.get("chain_hash")
        record_sans_chain = {k: v for k, v in record.items() if k != "chain_hash"}
        if claimed_chain_hash != _record_chain_hash(prev_hash, record_sans_chain):
            raise _fail("chain_hash mismatch (record mutated)")
        if record.get("kind") not in {kind.value for kind in EventKind}:
            raise _fail(f"unknown event kind {record.get('kind')!r}")
        if count == 0:
            if record.get("event") != GENESIS_EVENT or record.get("kind") != (
                EventKind.RUN_META.value
            ):
                raise _fail("genesis record is not the run binding")
            missing = [field for field in BINDING_FIELDS if payload.get(field) in (None, "", [])]
            if missing:
                raise _fail(f"genesis binding missing fields: {missing}")
        prev_hash = str(claimed_chain_hash)
        count += 1

    if count == 0:
        raise EvidenceIntegrityError(
            f"evidence log has no records: {path}", context={"path": str(path)}
        )

    head = ChainHead(count=count, chain_hash=prev_hash)
    if expected_head is not None and head != expected_head:
        raise EvidenceIntegrityError(
            "evidence chain head does not match the recorded run head "
            f"(recorded count={expected_head.count} hash={expected_head.chain_hash[:12]}…, "
            f"actual count={head.count} hash={head.chain_hash[:12]}…) — "
            "truncation or substitution",
            context={
                "path": str(path),
                "expected_count": expected_head.count,
                "actual_count": head.count,
            },
        )
    return head

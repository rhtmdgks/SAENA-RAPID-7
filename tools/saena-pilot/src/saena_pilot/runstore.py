"""Run metadata store — ALWAYS outside both repositories.

Layout: `<home>/pilot-runs/<run-id>/` where `<home>` is `$SAENA_PILOT_HOME`
(test override) or `~/.saena`. Creation refuses a store that resolves inside
either the RAPID-7 root or the customer repository — run metadata (contract,
reports, evidence) must never appear in either tree.

`run.json` is the resumable record: binding SHAs, contract hash, manifest
hash, mode history, and the evidence-chain head (count + hash) mirrored after
every append so chain truncation is detectable. Resume re-validates the
recorded RAPID-7 and customer HEADs against the current world and refuses on
mismatch (stale-run substitution defense).
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from saena_pilot._git import git_head_sha
from saena_pilot.errors import ResumeMismatchError, ValidationFailedError
from saena_pilot.evidence import ChainHead

RUN_SCHEMA_VERSION = "saena.pilot-run/v1"
_RUN_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "created_ts",
        "customer_repo",
        "domain",
        "customer_id",
        "rapid7_sha",
        "customer_sha",
        "contract_sha256",
        "manifest_sha256",
        "mode_history",
        "evidence_count",
        "evidence_head",
        "worktree_path",
    }
)


def new_run_id() -> str:
    return str(uuid.uuid4())


def pilot_home() -> Path:
    override = os.environ.get("SAENA_PILOT_HOME")
    if override:
        return Path(override)
    return Path.home() / ".saena"


def runs_root() -> Path:
    return pilot_home() / "pilot-runs"


def ensure_store_outside_repos(rapid7_root: Path, customer_root: Path | None) -> Path:
    """Fail-closed guard: the run store must not live inside either repo."""
    root = Path(os.path.realpath(runs_root()))
    repos = [Path(os.path.realpath(rapid7_root))]
    if customer_root is not None:
        repos.append(Path(os.path.realpath(customer_root)))
    for repo in repos:
        if root == repo or repo in root.parents:
            raise ValidationFailedError(
                f"run store {root} resolves inside repository {repo} — run metadata "
                "must never live in either repo (set SAENA_PILOT_HOME elsewhere)",
                context={"runs_root": str(root), "repo": str(repo)},
            )
    return root


@dataclass(slots=True)
class RunRecord:
    run_id: str
    created_ts: str
    customer_repo: str
    domain: str
    customer_id: str | None
    rapid7_sha: str
    customer_sha: str
    contract_sha256: str
    manifest_sha256: str
    mode_history: list[dict[str, Any]] = field(default_factory=list)
    evidence_count: int = 0
    evidence_head: str | None = None
    worktree_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": self.run_id,
            "created_ts": self.created_ts,
            "customer_repo": self.customer_repo,
            "domain": self.domain,
            "customer_id": self.customer_id,
            "rapid7_sha": self.rapid7_sha,
            "customer_sha": self.customer_sha,
            "contract_sha256": self.contract_sha256,
            "manifest_sha256": self.manifest_sha256,
            "mode_history": self.mode_history,
            "evidence_count": self.evidence_count,
            "evidence_head": self.evidence_head,
            "worktree_path": self.worktree_path,
        }

    @property
    def chain_head(self) -> ChainHead | None:
        if self.evidence_head is None or self.evidence_count <= 0:
            return None
        return ChainHead(count=self.evidence_count, chain_hash=self.evidence_head)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source: str) -> RunRecord:
        unknown = sorted(set(data) - _RUN_KEYS)
        if unknown:
            raise ValidationFailedError(
                f"run record {source} has unknown keys (rejected fail-closed): {unknown}",
                context={"source": source, "unknown_keys": unknown},
            )
        missing = sorted(_RUN_KEYS - set(data))
        if missing:
            raise ValidationFailedError(
                f"run record {source} is missing keys: {missing}",
                context={"source": source, "missing_keys": missing},
            )
        if data["schema_version"] != RUN_SCHEMA_VERSION:
            raise ValidationFailedError(
                f"run record {source} has schema_version {data['schema_version']!r}, "
                f"expected {RUN_SCHEMA_VERSION!r}",
                context={"source": source},
            )
        return cls(
            run_id=data["run_id"],
            created_ts=data["created_ts"],
            customer_repo=data["customer_repo"],
            domain=data["domain"],
            customer_id=data["customer_id"],
            rapid7_sha=data["rapid7_sha"],
            customer_sha=data["customer_sha"],
            contract_sha256=data["contract_sha256"],
            manifest_sha256=data["manifest_sha256"],
            mode_history=list(data["mode_history"]),
            evidence_count=int(data["evidence_count"]),
            evidence_head=data["evidence_head"],
            worktree_path=data["worktree_path"],
        )


def run_dir(run_id: str) -> Path:
    return runs_root() / run_id


def evidence_path(run_id: str) -> Path:
    return run_dir(run_id) / "events.jsonl"


def contract_path(run_id: str) -> Path:
    return run_dir(run_id) / "contract.json"


def create_run(
    *,
    customer_repo: Path,
    domain: str,
    customer_id: str | None,
    rapid7_sha: str,
    customer_sha: str,
    contract_sha256: str,
    manifest_sha256: str,
    mode: str,
) -> RunRecord:
    record = RunRecord(
        run_id=new_run_id(),
        created_ts=datetime.now(UTC).isoformat(),
        customer_repo=str(customer_repo),
        domain=domain,
        customer_id=customer_id,
        rapid7_sha=rapid7_sha,
        customer_sha=customer_sha,
        contract_sha256=contract_sha256,
        manifest_sha256=manifest_sha256,
        mode_history=[{"mode": mode, "ts": datetime.now(UTC).isoformat()}],
    )
    directory = run_dir(record.run_id)
    directory.mkdir(parents=True, exist_ok=False)
    save_run(record)
    return record


def save_run(record: RunRecord) -> None:
    """Atomic write (tmp + rename) of `run.json`."""
    directory = run_dir(record.run_id)
    target = directory / "run.json"
    tmp = directory / "run.json.tmp"
    tmp.write_text(json.dumps(record.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)


def load_run(run_id: str) -> RunRecord:
    path = run_dir(run_id) / "run.json"
    if not path.is_file():
        raise ValidationFailedError(
            f"run {run_id!r} not found under {runs_root()}",
            context={"run_id": run_id, "runs_root": str(runs_root())},
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationFailedError(
            f"run record {path} is not valid JSON: {exc}",
            context={"path": str(path)},
        ) from exc
    if not isinstance(data, dict):
        raise ValidationFailedError(
            f"run record {path} must be a JSON object",
            context={"path": str(path)},
        )
    return RunRecord.from_dict(data, source=str(path))


def list_runs() -> list[str]:
    root = runs_root()
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if (entry / "run.json").is_file())


def record_evidence_head(record: RunRecord, head: ChainHead) -> None:
    record.evidence_count = head.count
    record.evidence_head = head.chain_hash
    save_run(record)


def validate_resume(record: RunRecord, *, rapid7_root: Path) -> None:
    """Refuse resume unless the recorded world still exists exactly.

    Compares the recorded RAPID-7 HEAD and customer HEAD with the current
    ones; any mismatch raises `ResumeMismatchError` with an explicit
    expected-vs-actual report (stale-run substitution defense)."""
    current_rapid7 = git_head_sha(rapid7_root)
    customer_root = Path(record.customer_repo)
    current_customer = git_head_sha(customer_root) if customer_root.is_dir() else None

    mismatches: list[str] = []
    if current_rapid7 != record.rapid7_sha:
        mismatches.append(f"RAPID-7 HEAD: recorded {record.rapid7_sha}, current {current_rapid7}")
    if current_customer != record.customer_sha:
        mismatches.append(
            f"customer HEAD: recorded {record.customer_sha}, current {current_customer}"
        )
    if mismatches:
        raise ResumeMismatchError(
            "refusing to resume run "
            f"{record.run_id}: recorded state does not match the current world:\n  "
            + "\n  ".join(mismatches),
            context={"run_id": record.run_id, "mismatches": mismatches},
        )

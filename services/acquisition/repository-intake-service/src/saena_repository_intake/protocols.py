"""Thin adapter interfaces (`typing.Protocol`) for `saena_repository_intake`.

Pure structural-typing shapes only — NO implementation, NO real Git/network
I/O (mirrors `saena_domain.execution.protocols`' "typed I/O ports, no I/O in
the domain layer" discipline, applied one layer up at the service boundary).
Real Git clone / secret-scanning-tool / content-hash-verification
implementations are explicitly OUT of this patch unit's scope (mission:
"no real Git/network in unit tests — real clone is W3-later/integration") —
this module fixes the call shape a later integration unit's real adapters
must satisfy; `memory.py` in this same package ships only the bookkeeping
adapters that need no real external I/O
(`InMemoryIntakeManifestStore`/`InMemoryAuditSink`/`InMemoryWorkspaceStaging`).
`SecretScanner`/`ContentHashVerifier` fakes live in this patch unit's own
*test* factory module (`tests/unit/svc_repository_intake/intake_factories.py`)
since a fake standing in for real scanning/hashing logic is test-only by
nature, never a production adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from saena_domain.execution import JobContext
from saena_domain.identity import TenantId


@dataclass(frozen=True, slots=True)
class SecretScanResult:
    """Outcome of a `SecretScanner.scan` call.

    `redacted_summary` is a human-readable, ALREADY-REDACTED description a
    `SecretScanner` implementation prepares (e.g. `"1 finding: pattern
    'aws_secret_key' (redacted)"`) — this type does not itself redact
    anything (redaction of arbitrary scanner-tool output is an adapter
    concern, out of this pure-shape Protocol's scope); it only forbids the
    obviously-unsafe case of an empty/missing summary on a failed scan, so a
    caller cannot silently construct a `passed=False` result with no
    explanation at all.
    """

    passed: bool
    finding_count: int = 0
    redacted_summary: str = ""

    def __post_init__(self) -> None:
        if not self.passed and not self.redacted_summary:
            raise ValueError(
                "a failed SecretScanResult must carry a non-empty redacted_summary "
                "(structural guard — never silently unexplained)"
            )


@runtime_checkable
class SecretScanner(Protocol):
    """Secret scan gate that PRECEDES intake acceptance (Algorithm §5.4
    Input Gate). Never called with, and never expected to return, raw
    source content — it operates against a snapshot reference only."""

    def scan(self, *, snapshot_uri: str, content_hash: str) -> SecretScanResult:
        """Scan the snapshot identified by `snapshot_uri`/`content_hash` and
        report whether it is clean to accept."""
        ...


@runtime_checkable
class ContentHashVerifier(Protocol):
    """Verifies a snapshot's actual content matches its claimed
    `content_hash` (`sha256:<64-hex>`, mission item 2)."""

    def verify(self, *, snapshot_uri: str, expected_hash: str) -> bool:
        """Return `True` iff the content addressed by `snapshot_uri`
        actually hashes to `expected_hash`."""
        ...


@runtime_checkable
class WorkspaceStaging(Protocol):
    """Per-run isolated workspace lease (CLAUDE.md Constraints: "Customer
    source only in isolated per-run workspace") — `core.perform_intake`
    always releases whatever it acquires, success or failure alike (mission
    item 8: "partial intake cleanup on failure, no half-state")."""

    def acquire(self, *, job_context: JobContext) -> str:
        """Allocate an isolated staging workspace for this job run, return
        an opaque handle."""
        ...

    def release(self, *, workspace_handle: str) -> None:
        """Release/clean up the workspace identified by `workspace_handle`.

        MUST be safe to call exactly once per successful `acquire` and MUST
        NOT raise for an already-released handle in a well-behaved
        implementation — `core.perform_intake` calls this unconditionally in
        a `finally` block."""
        ...


@runtime_checkable
class IntakeManifestStore(Protocol):
    """Immutable `IntakeManifest` store — put-once by `(tenant_id,
    content_hash)` (contract-catalog.md SourceSnapshot row: "Idempotency
    key: repo SHA (content hash)"). ONLY an ACCEPTED decision is ever
    stored here (mission item 8: a REFUSED decision never reaches this
    port at all — see `core.perform_intake`), so this store can never hold
    half-written/partial state.
    """

    def put(
        self, tenant_id: TenantId, content_hash: str, manifest: dict[str, Any]
    ) -> dict[str, Any]:
        """Store `manifest` under `(tenant_id, content_hash)`.

        Returns a deep copy of the stored manifest (fresh write or
        idempotent replay alike). Raises
        `saena_repository_intake.errors.DuplicateIntakeConflictError` if the
        key already holds DIFFERENT manifest content."""
        ...

    def get(self, tenant_id: TenantId, content_hash: str) -> dict[str, Any]:
        """Return a deep copy of the stored manifest for this key.

        Raises `saena_repository_intake.errors.IntakeManifestNotFoundError`
        if absent."""
        ...


@runtime_checkable
class AuditSink(Protocol):
    """Records one structured event per intake DECISION (mission item 11:
    "audit event on every decision") — accepted, refused, or replayed
    alike. `event` is a plain, already-redacted `dict` (never raw secret
    content, never a stack trace); this Protocol does not itself redact —
    `core.perform_intake` never builds an `event` dict from anything but
    already-safe structural fields."""

    def record(self, event: dict[str, Any]) -> None: ...


__all__ = [
    "AuditSink",
    "ContentHashVerifier",
    "IntakeManifestStore",
    "SecretScanResult",
    "SecretScanner",
    "WorkspaceStaging",
]

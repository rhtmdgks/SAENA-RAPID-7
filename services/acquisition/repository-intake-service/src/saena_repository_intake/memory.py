"""In-memory reference adapters for `saena_repository_intake` (mirrors
`saena_domain.persistence.memory`'s own module docstring pattern: pure
Python, no SQL/Kafka/real-Git/network I/O — used by tests and by any caller
that does not yet need a real backing store).

Ships only the THREE ports whose reference implementation needs no real
external I/O: `IntakeManifestStore` (a dict), `AuditSink` (structured
logging), `WorkspaceStaging` (a counter). `SecretScanner`/
`ContentHashVerifier` have NO adapter here — a real implementation of either
requires actual Git/network access (secret-scanning-tool integration,
content re-hashing against a real clone), explicitly out of this patch
unit's scope (mission: "real clone is W3-later/integration"); test-only
fakes for both live in this patch unit's test factory module instead
(`tests/unit/svc_repository_intake/intake_factories.py`).
"""

from __future__ import annotations

import copy
import threading
from typing import Any

from saena_domain.execution import JobContext
from saena_domain.identity import TenantId
from saena_observability.logging import get_logger

from saena_repository_intake.errors import DuplicateIntakeConflictError, IntakeManifestNotFoundError

_logger = get_logger("saena_repository_intake")


class InMemoryIntakeManifestStore:
    """Reference `IntakeManifestStore` — put-once by `(tenant_id,
    content_hash)`.

    Defensive copies (mirrors `saena_domain.persistence.memory.
    InMemoryArtifactManifestStore`): both the stored copy and every returned
    copy go through `copy.deepcopy` — mutating a returned manifest dict can
    never corrupt this store's own internal state, or vice versa.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # tenant_id -> content_hash -> manifest
        self._store: dict[str, dict[str, dict[str, Any]]] = {}

    def put(
        self, tenant_id: TenantId, content_hash: str, manifest: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            tenant_store = self._store.setdefault(tenant_id.value, {})
            existing = tenant_store.get(content_hash)
            if existing is not None:
                if existing == manifest:
                    return copy.deepcopy(existing)
                raise DuplicateIntakeConflictError(
                    f"content_hash {content_hash!r} already stored with different manifest",
                    context={"tenant_id": tenant_id.value, "content_hash": content_hash},
                )
            stored = copy.deepcopy(manifest)
            tenant_store[content_hash] = stored
            return copy.deepcopy(stored)

    def get(self, tenant_id: TenantId, content_hash: str) -> dict[str, Any]:
        with self._lock:
            manifest = self._store.get(tenant_id.value, {}).get(content_hash)
        if manifest is None:
            raise IntakeManifestNotFoundError(
                f"no intake manifest stored for content_hash {content_hash!r}",
                context={"tenant_id": tenant_id.value, "content_hash": content_hash},
            )
        return copy.deepcopy(manifest)


class InMemoryAuditSink:
    """Reference `AuditSink` — an append-only in-process list, for tests and
    any pre-real-audit-ledger caller. `saena_domain.persistence.ports.
    AuditLedgerPort`/`InMemoryAuditLedger` (hash-chained, per-tenant) is the
    eventual real audit trail this event would also feed — wiring THAT
    integration is out of this patch unit's scope; this class only proves
    "an audit event was recorded for every decision" at the unit-test
    level.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []

    def record(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(copy.deepcopy(event))

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(copy.deepcopy(event) for event in self._events)


class LoggingAuditSink:
    """`AuditSink` that structured-logs every decision (mirrors
    `saena_artifact_registry.app`'s `_logger.info("artifact manifest
    registered", extra={...})` call-site pattern) — the default production
    stand-in until a real `AuditLedgerPort` wiring lands."""

    def __init__(self) -> None:
        self._logger = _logger

    def record(self, event: dict[str, Any]) -> None:
        self._logger.info(
            "repository intake decision",
            extra={"saena_attributes": {f"repository_intake.{k}": v for k, v in event.items()}},
        )


class InMemoryWorkspaceStaging:
    """Reference `WorkspaceStaging` — hands out monotonically increasing
    opaque handles and tracks which are currently leased, so a test can
    assert every `acquire` is matched by exactly one `release` (mission item
    8, "partial intake cleanup on failure").
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 0
        self._leased: set[str] = set()
        self._released: set[str] = set()

    def acquire(self, *, job_context: JobContext) -> str:
        with self._lock:
            self._next_id += 1
            handle = f"workspace-{job_context.run_id}-{self._next_id}"
            self._leased.add(handle)
            return handle

    def release(self, *, workspace_handle: str) -> None:
        with self._lock:
            self._leased.discard(workspace_handle)
            self._released.add(workspace_handle)

    @property
    def outstanding(self) -> frozenset[str]:
        """Handles `acquire`d but never `release`d — MUST be empty after
        every `core.perform_intake` call, success or failure alike."""
        with self._lock:
            return frozenset(self._leased)


__all__ = [
    "InMemoryAuditSink",
    "InMemoryIntakeManifestStore",
    "InMemoryWorkspaceStaging",
    "LoggingAuditSink",
]

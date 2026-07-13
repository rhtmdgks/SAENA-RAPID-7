"""saena_repository_intake — `repository-intake-service` (W3, `JobKind.
REPOSITORY_INTAKE`): the Algorithm §5.4 Input Gate for customer
`SourceSnapshot` intake.

Pure-domain core (`core.perform_intake`) + thin adapter Protocols
(`protocols.py`) with in-memory reference adapters (`memory.py`) for the
ports that need no real Git/network I/O, plus a thin FastAPI adapter
(`app.py`) mirroring `saena_artifact_registry`'s shape. See `core.py`'s
module docstring for the full Input Gate write-up and
`docs/architecture/execution-runtime.md` for this `JobKind`'s bounded
context.
"""

from __future__ import annotations

from saena_repository_intake.core import (
    ALLOWED_SNAPSHOT_URI_SCHEMES,
    ALLOWED_SOURCE_TYPES,
    THIS_JOB_KIND,
    IntakeDecision,
    IntakeManifest,
    IntakeOutcome,
    SnapshotReference,
    parse_snapshot_reference,
    perform_intake,
    validate_source_uri,
)
from saena_repository_intake.errors import (
    ContentHashMismatchError,
    CrossTenantSourceError,
    DuplicateIntakeConflictError,
    ForbiddenUriError,
    InlineContentForbiddenError,
    IntakeManifestNotFoundError,
    MalformedIntakeRequestError,
    RepositoryIntakeError,
    SecretScanFailedError,
    UnsupportedSourceTypeError,
)
from saena_repository_intake.memory import (
    InMemoryAuditSink,
    InMemoryIntakeManifestStore,
    InMemoryWorkspaceStaging,
    LoggingAuditSink,
)
from saena_repository_intake.protocols import (
    AuditSink,
    ContentHashVerifier,
    IntakeManifestStore,
    SecretScanner,
    SecretScanResult,
    WorkspaceStaging,
)

__all__ = [
    "ALLOWED_SNAPSHOT_URI_SCHEMES",
    "ALLOWED_SOURCE_TYPES",
    "THIS_JOB_KIND",
    "AuditSink",
    "ContentHashMismatchError",
    "ContentHashVerifier",
    "CrossTenantSourceError",
    "DuplicateIntakeConflictError",
    "ForbiddenUriError",
    "InMemoryAuditSink",
    "InMemoryIntakeManifestStore",
    "InMemoryWorkspaceStaging",
    "InlineContentForbiddenError",
    "IntakeDecision",
    "IntakeManifest",
    "IntakeManifestNotFoundError",
    "IntakeManifestStore",
    "IntakeOutcome",
    "LoggingAuditSink",
    "MalformedIntakeRequestError",
    "RepositoryIntakeError",
    "SecretScanFailedError",
    "SecretScanResult",
    "SecretScanner",
    "SnapshotReference",
    "UnsupportedSourceTypeError",
    "WorkspaceStaging",
    "parse_snapshot_reference",
    "perform_intake",
    "validate_source_uri",
]

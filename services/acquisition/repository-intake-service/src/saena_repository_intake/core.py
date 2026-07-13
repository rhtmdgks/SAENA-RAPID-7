"""Pure-domain repository-intake core — Algorithm §5.4 "Input Gate".

`perform_intake` is the single entry point: given an inbound
snapshot-reference payload and the job's `JobContext` (execution identity,
`saena_domain.execution`), it runs the full Input Gate in a fixed order and
returns an `IntakeOutcome` on acceptance or raises a
`saena_repository_intake.errors.RepositoryIntakeError` subclass on refusal.
Every dependency (secret scanning, content-hash verification, manifest
storage, audit recording, workspace staging) is injected as a
`protocols.py` Protocol — this module performs NO I/O of its own (mirrors
`saena_domain.policy`/`saena_domain.execution`'s "pure/deterministic, ports
injected" discipline, one layer up at the service boundary).

Fixed gate order (each step short-circuits the rest on failure):

1. reject inline content (`InlineContentForbiddenError`) — structural, on
   the raw payload's keys, before any other field is even read.
2. parse + structurally validate required fields, including allowed
   `source_type` (`UnsupportedSourceTypeError`) and `sha256_ref`/`git_sha`
   shape (`MalformedIntakeRequestError`).
3. idempotency lookup by `(JobContext.tenant_id, content_hash)`
   (contract-catalog.md SourceSnapshot idempotency key) — an identical
   resend short-circuits straight to a replay outcome (no re-scan, no
   double effect); a resend with the SAME key but DIFFERENT identifying
   fields is a hard conflict (`DuplicateIntakeConflictError`).
4. cross-tenant check: snapshot's own `tenant_id` vs. `JobContext.tenant_id`
   (`CrossTenantSourceError`).
5. forbidden-uri check on `snapshot_uri`/`sbom_uri` (`ForbiddenUriError`).
6. content-hash verification (`ContentHashMismatchError`).
7. secret scan — PRECEDES acceptance (`SecretScanFailedError`); a flagged
   snapshot is refused and the run stops here, before any manifest is ever
   built or stored.
8. build the immutable `IntakeManifest`, store it (idempotent put), build
   the `repo.intaken.v1` event payload.

An `AuditSink.record` call is made for EVERY decision reached (mission item
11) — accepted, replayed, or any refusal — via `_audit`. A `WorkspaceStaging`
lease is acquired once at the top and released exactly once in a `finally`
block, so a lease is always cleaned up regardless of which gate stops the
run (mission item 8, "no half-state").
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from saena_domain.execution import JobContext, JobKind, build_repo_intaken_payload, profile_for
from saena_domain.identity import TenantId

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
from saena_repository_intake.protocols import (
    AuditSink,
    ContentHashVerifier,
    IntakeManifestStore,
    SecretScanner,
    WorkspaceStaging,
)

#: This service's `JobKind` (ADR-0004 3-way runner-pool SA split: "repository-intake:
#: read-only Git만"). Asserted below, once, at import time — a documentation-as-code
#: guard that this module never drifts from the execution-domain layer's own fact.
THIS_JOB_KIND = JobKind.REPOSITORY_INTAKE
assert profile_for(THIS_JOB_KIND).read_only is True  # noqa: S101 — import-time invariant, not a test

#: `source-snapshot.schema.json` `source_type` enum — closed set (mission item 4).
ALLOWED_SOURCE_TYPES: frozenset[str] = frozenset({"git", "zip"})

#: Closed set of `snapshot_uri`/`sbom_uri` schemes this service accepts. `git`/`https`
#: cover a real repository host or a signed-but-opaque snapshot fetch location; `blob`
#: covers a same-scheme reference into `artifact-registry-service`'s own opaque
#: `blob://<tenant_id>/<sha256>` gateway (see that service's `app.py`
#: `_blob_scheme_uri`) for a pre-staged snapshot. This is this patch unit's own
#: reasoned proposal (no ADR names the exact scheme allow-list) — a later unit
#: reconciling real Git-host onboarding should revisit this set, not silently widen it.
ALLOWED_SNAPSHOT_URI_SCHEMES: frozenset[str] = frozenset({"git", "https", "blob"})

# Verbatim from common/identifiers/v1#/$defs/uri_ref — query/fragment forbidden
# (ADR-0024(f) ruling R9-5, presigned-token-smuggling defense). Duplicated here (not
# imported) for the same reason `identity.tenant.TENANT_ID_PATTERN` documents: no
# importable Python constant exists for a $defs-only JSON Schema file outside the
# generated pydantic model.
_URI_SHAPE_PATTERN = re.compile(r"^([a-z0-9+.-]+)://[^?#]+$")
# common/identifiers/v1#/$defs/sha256_ref
_SHA256_REF_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
# common/identifiers/v1#/$defs/git_sha
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

#: Fields a well-formed intake request payload MUST carry — exactly the
#: `SourceSnapshot` contract fields this service itself determines
#: (`secret_scan_status`/`captured_at` timing note below).
_REQUIRED_REQUEST_FIELDS: frozenset[str] = frozenset(
    {
        "tenant_id",
        "run_id",
        "repo_commit",
        "content_hash",
        "snapshot_uri",
        "source_type",
        "sbom_uri",
        "captured_at",
    }
)

#: Field names that would carry inline source content if present — mission item 5,
#: "inline source content FORBIDDEN — only immutable snapshot references". Checked
#: BEFORE any other field is read, so an inline-content payload is refused
#: structurally, never partially processed.
_FORBIDDEN_INLINE_CONTENT_FIELDS: frozenset[str] = frozenset(
    {
        "content",
        "content_base64",
        "blob_base64",
        "inline_content",
        "file_contents",
        "source_content",
        "raw_content",
        "payload_base64",
    }
)


class IntakeDecision(StrEnum):
    """Outcome of the Input Gate for one intake attempt."""

    ACCEPTED = "accepted"
    REFUSED = "refused"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True)
class SnapshotReference:
    """Parsed, structurally-valid inbound intake request — a REFERENCE ONLY
    (no field on this type can carry inline content; mission item 5 is
    enforced by this type's very shape, not just by a runtime check)."""

    tenant_id: str
    run_id: str
    repo_commit: str
    content_hash: str
    snapshot_uri: str
    source_type: str
    sbom_uri: str
    captured_at: str


@dataclass(frozen=True, slots=True)
class IntakeManifest:
    """Immutable input manifest — snapshot ref + content hash + intake
    decision (mission item 6). Frozen dataclass: no field can be reassigned
    after construction."""

    tenant_id: str
    run_id: str
    idempotency_key: str
    repo_commit: str
    content_hash: str
    snapshot_uri: str
    source_type: str
    sbom_uri: str
    secret_scan_status: str
    captured_at: str
    decision: IntakeDecision

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decision"] = self.decision.value
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> IntakeManifest:
        data = dict(payload)
        data["decision"] = IntakeDecision(data["decision"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class IntakeOutcome:
    """Result of a successful (accepted or idempotently replayed)
    `perform_intake` call."""

    manifest: IntakeManifest
    event_payload: dict[str, Any]
    replayed: bool


def _reject_inline_content(payload: Mapping[str, Any]) -> None:
    forbidden_present = _FORBIDDEN_INLINE_CONTENT_FIELDS & payload.keys()
    if forbidden_present:
        raise InlineContentForbiddenError(
            "intake payload carries inline source content — only immutable "
            "snapshot references are accepted",
            context={"forbidden_fields": sorted(forbidden_present)},
        )


def _require_non_empty_str(payload: Mapping[str, Any], field_name: str) -> str:
    if field_name not in payload:
        raise MalformedIntakeRequestError(
            f"missing required field {field_name!r}", context={"field": field_name}
        )
    value = payload[field_name]
    if not isinstance(value, str) or not value:
        raise MalformedIntakeRequestError(
            f"{field_name} must be a non-empty string", context={"field": field_name}
        )
    return value


def parse_snapshot_reference(payload: Mapping[str, Any]) -> SnapshotReference:
    """Parse+validate a raw intake payload into a `SnapshotReference`.

    Raises `InlineContentForbiddenError`, `MalformedIntakeRequestError`, or
    `UnsupportedSourceTypeError` — never partially constructs a
    `SnapshotReference` on any failure.
    """
    _reject_inline_content(payload)

    unexpected = set(payload.keys()) - _REQUIRED_REQUEST_FIELDS
    if unexpected:
        raise MalformedIntakeRequestError(
            "intake payload carries unrecognized field(s) outside the snapshot-reference contract",
            context={"unexpected_fields": sorted(unexpected)},
        )

    tenant_id = _require_non_empty_str(payload, "tenant_id")
    run_id = _require_non_empty_str(payload, "run_id")
    repo_commit = _require_non_empty_str(payload, "repo_commit")
    content_hash = _require_non_empty_str(payload, "content_hash")
    snapshot_uri = _require_non_empty_str(payload, "snapshot_uri")
    source_type = _require_non_empty_str(payload, "source_type")
    sbom_uri = _require_non_empty_str(payload, "sbom_uri")
    captured_at = _require_non_empty_str(payload, "captured_at")

    if source_type not in ALLOWED_SOURCE_TYPES:
        raise UnsupportedSourceTypeError(
            f"source_type {source_type!r} is not supported",
            context={"source_type": source_type, "allowed": sorted(ALLOWED_SOURCE_TYPES)},
        )
    if not _GIT_SHA_PATTERN.fullmatch(repo_commit):
        raise MalformedIntakeRequestError(
            f"repo_commit {repo_commit!r} is not a full 40-hex git SHA",
            context={"field": "repo_commit"},
        )
    if not _SHA256_REF_PATTERN.fullmatch(content_hash):
        raise MalformedIntakeRequestError(
            f"content_hash {content_hash!r} is not `sha256:<64-hex>`",
            context={"field": "content_hash"},
        )

    return SnapshotReference(
        tenant_id=tenant_id,
        run_id=run_id,
        repo_commit=repo_commit,
        content_hash=content_hash,
        snapshot_uri=snapshot_uri,
        source_type=source_type,
        sbom_uri=sbom_uri,
        captured_at=captured_at,
    )


def validate_source_uri(uri: str, *, field_name: str) -> None:
    """Reject a forbidden source uri: missing scheme, `?`/`#` present
    (ADR-0024(f) R9-5), or a scheme outside `ALLOWED_SNAPSHOT_URI_SCHEMES`
    (mission item 9)."""
    match = _URI_SHAPE_PATTERN.fullmatch(uri)
    if match is None:
        raise ForbiddenUriError(
            f"{field_name} is not a valid reference-only uri (scheme required, "
            "'?'/'#' forbidden — presigned-token smuggling defense)",
            context={"field": field_name},
        )
    scheme = match.group(1)
    if scheme not in ALLOWED_SNAPSHOT_URI_SCHEMES:
        raise ForbiddenUriError(
            f"{field_name} scheme {scheme!r} is not in the allowed set "
            f"{sorted(ALLOWED_SNAPSHOT_URI_SCHEMES)!r}",
            context={"field": field_name, "scheme": scheme},
        )


def _identifying_fields(reference: SnapshotReference) -> dict[str, str]:
    """The subset of `SnapshotReference` fields that must match byte-for-byte
    across a resend under the same idempotency key for it to count as a
    replay rather than a conflict."""
    return {
        "repo_commit": reference.repo_commit,
        "content_hash": reference.content_hash,
        "snapshot_uri": reference.snapshot_uri,
        "source_type": reference.source_type,
        "sbom_uri": reference.sbom_uri,
    }


def _audit(
    audit_sink: AuditSink,
    *,
    decision: IntakeDecision,
    job_context: JobContext,
    content_hash: str | None,
    error_code: str | None = None,
) -> None:
    event: dict[str, Any] = {
        "decision": decision.value,
        "job_kind": THIS_JOB_KIND.value,
        "tenant_id": job_context.tenant_id,
        "run_id": job_context.run_id,
        "idempotency_key": job_context.idempotency_key,
        "content_hash": content_hash,
    }
    if error_code is not None:
        event["error_code"] = error_code
    audit_sink.record(event)


def perform_intake(
    *,
    payload: Mapping[str, Any],
    job_context: JobContext,
    hash_verifier: ContentHashVerifier,
    secret_scanner: SecretScanner,
    manifest_store: IntakeManifestStore,
    audit_sink: AuditSink,
    workspace: WorkspaceStaging,
) -> IntakeOutcome:
    """Run the full Input Gate for one intake attempt. See module docstring
    for the fixed gate order. Raises a `RepositoryIntakeError` subclass on
    any refusal; returns `IntakeOutcome` on acceptance or idempotent
    replay."""
    workspace_handle = workspace.acquire(job_context=job_context)
    tenant_id = TenantId(job_context.tenant_id)
    try:
        try:
            reference = parse_snapshot_reference(payload)
        except RepositoryIntakeError as exc:
            _audit(
                audit_sink,
                decision=IntakeDecision.REFUSED,
                job_context=job_context,
                content_hash=None,
                error_code=exc.error_code,
            )
            raise

        try:
            existing = manifest_store.get(tenant_id, reference.content_hash)
        except IntakeManifestNotFoundError:
            existing = None

        if existing is not None:
            existing_manifest = IntakeManifest.from_dict(existing)
            existing_identity = {
                "repo_commit": existing_manifest.repo_commit,
                "content_hash": existing_manifest.content_hash,
                "snapshot_uri": existing_manifest.snapshot_uri,
                "source_type": existing_manifest.source_type,
                "sbom_uri": existing_manifest.sbom_uri,
            }
            if existing_identity != _identifying_fields(reference):
                conflict = DuplicateIntakeConflictError(
                    f"content_hash {reference.content_hash!r} already intaken with "
                    "different identifying fields",
                    context={
                        "content_hash": reference.content_hash,
                        "tenant_id": job_context.tenant_id,
                    },
                )
                _audit(
                    audit_sink,
                    decision=IntakeDecision.REFUSED,
                    job_context=job_context,
                    content_hash=reference.content_hash,
                    error_code=conflict.error_code,
                )
                raise conflict
            _audit(
                audit_sink,
                decision=IntakeDecision.REPLAYED,
                job_context=job_context,
                content_hash=reference.content_hash,
            )
            event_payload = build_repo_intaken_payload(
                repo_commit=existing_manifest.repo_commit,
                content_hash=existing_manifest.content_hash,
                snapshot_uri=existing_manifest.snapshot_uri,
            )
            return IntakeOutcome(
                manifest=existing_manifest, event_payload=event_payload, replayed=True
            )

        try:
            if reference.tenant_id != job_context.tenant_id:
                raise CrossTenantSourceError(
                    "snapshot tenant_id does not match the authenticated JobContext tenant_id",
                    context={
                        "snapshot_tenant_id": reference.tenant_id,
                        "job_context_tenant_id": job_context.tenant_id,
                    },
                )

            validate_source_uri(reference.snapshot_uri, field_name="snapshot_uri")
            validate_source_uri(reference.sbom_uri, field_name="sbom_uri")

            if not hash_verifier.verify(
                snapshot_uri=reference.snapshot_uri, expected_hash=reference.content_hash
            ):
                raise ContentHashMismatchError(
                    "snapshot content does not match the claimed content_hash",
                    context={
                        "snapshot_uri": reference.snapshot_uri,
                        "content_hash": reference.content_hash,
                    },
                )

            scan_result = secret_scanner.scan(
                snapshot_uri=reference.snapshot_uri, content_hash=reference.content_hash
            )
            if not scan_result.passed:
                raise SecretScanFailedError(
                    "secret scan flagged the snapshot; intake refused, run stopped",
                    context={
                        "finding_count": scan_result.finding_count,
                        "redacted_summary": scan_result.redacted_summary,
                    },
                )
        except RepositoryIntakeError as exc:
            _audit(
                audit_sink,
                decision=IntakeDecision.REFUSED,
                job_context=job_context,
                content_hash=reference.content_hash,
                error_code=exc.error_code,
            )
            raise

        manifest = IntakeManifest(
            tenant_id=job_context.tenant_id,
            run_id=job_context.run_id,
            idempotency_key=job_context.idempotency_key,
            repo_commit=reference.repo_commit,
            content_hash=reference.content_hash,
            snapshot_uri=reference.snapshot_uri,
            source_type=reference.source_type,
            sbom_uri=reference.sbom_uri,
            secret_scan_status="passed",
            captured_at=reference.captured_at,
            decision=IntakeDecision.ACCEPTED,
        )
        stored = manifest_store.put(tenant_id, reference.content_hash, manifest.to_dict())
        stored_manifest = IntakeManifest.from_dict(stored)
        event_payload = build_repo_intaken_payload(
            repo_commit=stored_manifest.repo_commit,
            content_hash=stored_manifest.content_hash,
            snapshot_uri=stored_manifest.snapshot_uri,
        )
        _audit(
            audit_sink,
            decision=IntakeDecision.ACCEPTED,
            job_context=job_context,
            content_hash=stored_manifest.content_hash,
        )
        return IntakeOutcome(manifest=stored_manifest, event_payload=event_payload, replayed=False)
    finally:
        workspace.release(workspace_handle=workspace_handle)


__all__ = [
    "ALLOWED_SNAPSHOT_URI_SCHEMES",
    "ALLOWED_SOURCE_TYPES",
    "THIS_JOB_KIND",
    "IntakeDecision",
    "IntakeManifest",
    "IntakeOutcome",
    "SnapshotReference",
    "parse_snapshot_reference",
    "perform_intake",
    "validate_source_uri",
]

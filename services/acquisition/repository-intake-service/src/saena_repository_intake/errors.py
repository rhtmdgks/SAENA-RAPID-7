"""Exception hierarchy for `saena_repository_intake`.

Same shape as `saena_artifact_registry.errors` / `saena_domain.persistence.
errors` (`saena.<category>.<reason>` `error_code` + structured, log-safe
`context` dict, ADR-0015 9-category taxonomy) so `problem.py`'s RFC 9457
mapper can build a `ProblemDetail` directly from any of these, AND so
`to_job_error()` below can hand every refusal to the caller as a
`saena_domain.execution.JobError` (ADR-0015 canonical error model) without a
second translation table.

`context` on every subclass here is structural only (field names, allowed
sets, tenant ids, uris) — NEVER a raw secret value or source content
(mirrors `saena_artifact_registry.errors`' "context never blob content"
discipline, applied here to "never a raw secret finding" — see
`SecretScanFailedError`'s own docstring for the sharpest instance of this
rule).
"""

from __future__ import annotations

from typing import Any

from saena_domain.execution import JobError


class RepositoryIntakeError(Exception):
    """Base class for every error raised by `saena_repository_intake`."""

    error_code: str = "saena.internal.repository_intake_error"
    status_code: int = 500
    retryable: bool = False

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}

    def to_job_error(self) -> JobError:
        """Render this refusal as a `saena_domain.execution.JobError`
        (mission: "intake refused with a JobError").

        `redacted_detail` is built from `self.context`, stringified —
        `JobError.__post_init__` itself rejects any value that looks
        stack-trace-shaped or is oversized, giving a second, structural
        backstop on top of every subclass's own "never a raw secret" rule.
        """
        redacted_detail = {key: str(value) for key, value in self.context.items()}
        return JobError(
            error_code=self.error_code,
            summary=str(self),
            retryable=self.retryable,
            redacted_detail=redacted_detail,
        )


class MalformedIntakeRequestError(RepositoryIntakeError):
    """The intake request payload is missing a required field, or a field
    fails its contract-level shape check (sha256_ref / git_sha / uri_ref
    pattern) — structural validation, ahead of any domain decision."""

    error_code = "saena.validation.malformed_intake_request"
    status_code = 400


class InlineContentForbiddenError(RepositoryIntakeError):
    """The intake payload carries an inline-content-shaped field (e.g.
    `content_base64`) — repository-intake accepts IMMUTABLE SNAPSHOT
    REFERENCES ONLY (mission item 5 / SourceSnapshot schema `$comment`:
    "Never carries source content or file listings"). Rejected before any
    other validation runs."""

    error_code = "saena.validation.inline_content_forbidden"
    status_code = 400


class UnsupportedSourceTypeError(RepositoryIntakeError):
    """`source_type` is outside the closed `{"git", "zip"}` set
    (`source-snapshot.schema.json` `source_type` enum)."""

    error_code = "saena.validation.unsupported_source_type"
    status_code = 400


class ForbiddenUriError(RepositoryIntakeError):
    """A `*_uri` field is not a valid reference-only uri: missing scheme,
    carries a `?`/`#` (ADR-0024(f) ruling R9-5 presigned-token-smuggling
    defense — verbatim `uri_ref` pattern), or uses a scheme outside this
    module's closed `ALLOWED_SNAPSHOT_URI_SCHEMES` set."""

    error_code = "saena.validation.forbidden_source_uri"
    status_code = 400


class CrossTenantSourceError(RepositoryIntakeError):
    """The snapshot's own `tenant_id` does not match the authenticated
    `JobContext.tenant_id` (mission item 10) — refused, never silently
    reassigned to the caller's tenant."""

    error_code = "saena.policy_denied.cross_tenant_source"
    status_code = 403


class ContentHashMismatchError(RepositoryIntakeError):
    """`ContentHashVerifier.verify` reports the snapshot's actual content
    does not match the claimed `content_hash` (mission item 2)."""

    error_code = "saena.validation.content_hash_mismatch"
    status_code = 400


class SecretScanFailedError(RepositoryIntakeError):
    """A `SecretScanner` flagged the snapshot — intake refused, run stopped
    (mission item 3, Algorithm §5.4 Input Gate).

    `context` carries ONLY structural scan metadata (`finding_count`,
    `redacted_summary` — the latter itself guaranteed pre-redacted by the
    `SecretScanner` contract, see `protocols.SecretScanResult`) — this
    class, like every other error here, never accepts a raw secret value as
    a constructor argument in the first place, so there is no code path by
    which one could reach `context`/`to_job_error()`/an audit sink/a log
    line through this exception type.
    """

    error_code = "saena.policy_denied.secret_scan_failed"
    status_code = 403


class DuplicateIntakeConflictError(RepositoryIntakeError):
    """A resend under the same idempotency key (`content_hash`, per
    `contract-catalog.md`'s SourceSnapshot row "Idempotency key: repo SHA
    (content hash)") carries DIFFERENT identifying fields than the
    already-accepted manifest on record — a hard conflict, never a silent
    overwrite (mirrors `saena_artifact_registry.errors.
    DuplicateArtifactConflictError` / `saena_domain.persistence.errors.
    DuplicateManifestError`)."""

    error_code = "saena.conflict.duplicate_intake"
    status_code = 409


class IntakeManifestNotFoundError(RepositoryIntakeError):
    """No manifest exists for the requested key (within the caller's own
    tenant)."""

    error_code = "saena.not_found.intake_manifest"
    status_code = 404


__all__ = [
    "ContentHashMismatchError",
    "CrossTenantSourceError",
    "DuplicateIntakeConflictError",
    "ForbiddenUriError",
    "InlineContentForbiddenError",
    "IntakeManifestNotFoundError",
    "MalformedIntakeRequestError",
    "RepositoryIntakeError",
    "SecretScanFailedError",
    "UnsupportedSourceTypeError",
]

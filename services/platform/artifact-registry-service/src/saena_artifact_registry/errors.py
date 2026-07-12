"""Exception hierarchy for `saena_artifact_registry`.

Follows the same shape as `saena_domain.persistence.errors` /
`saena_domain.identity.errors` (`saena.<category>.<reason>` `error_code` +
structured, log-safe `context` dict, ADR-0015 taxonomy) so `problem.py`'s
RFC 9457 mapper can build a `ProblemDetail`
(`saena_schemas.common.problem_detail_v1`) directly from any of these without
a second translation table.
"""

from __future__ import annotations

from typing import Any


class ArtifactRegistryError(Exception):
    """Base class for every error raised by `saena_artifact_registry`.

    Attributes:
        error_code: `saena.<category>.<reason>` taxonomy string (ADR-0015).
        context: structured, log-safe data describing the violation — never
            blob content, never raw manifest bytes (customer-proprietary MAX
            sensitivity, contract-catalog.md PatchArtifact row).
    """

    error_code: str = "saena.artifact_registry.error"
    status_code: int = 500
    retryable: bool = False

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        """Structured, log-safe representation for audit/observability sinks."""
        return {"error_code": self.error_code, "message": str(self), **self.context}


class InvalidUriFieldError(ArtifactRegistryError):
    """A manifest `uri`-shaped field violates ADR-0024(f)'s common pattern
    (`^[a-z0-9+.-]+://[^?#]+$` — scheme required, `?`/`#` forbidden).

    Raised structurally, ahead of storage — the whole point of ADR-0024(f)
    is that a presigned-URL token (typically carried in a `?`-delimited
    query string, e.g. `?X-Amz-Signature=...`) can never reach a stored
    manifest, audit trail, or log line via this field.
    """

    error_code = "saena.validation.uri_field_invalid"
    status_code = 400


class DuplicateArtifactConflictError(ArtifactRegistryError):
    """`POST /v1/artifacts` was called twice for the same
    `(patch_unit_id, worktree_commit)` key with DIFFERENT manifest content.

    Mirrors `saena_domain.persistence.errors.DuplicateManifestError` at the
    HTTP boundary (409) — manifest immutability (W2B exit criterion) means a
    second `put` under the same key with the SAME content is an idempotent
    no-op, but different content is a hard conflict.
    """

    error_code = "saena.conflict.duplicate_artifact_manifest"
    status_code = 409


class ArtifactNotFoundError(ArtifactRegistryError):
    """No manifest/blob exists for the requested key (within the caller's
    own tenant)."""

    error_code = "saena.not_found.artifact_manifest"
    status_code = 404


class BlobGatewayDeniedError(ArtifactRegistryError):
    """A caller attempted to fetch a blob outside the single-gateway path,
    or under a `tenant_id` that does not own the referenced blob
    (W2B exit "blob 단일 관문 검증" / bypass-blocked test).

    Deliberately mapped to 404 (never leaking whether the blob exists under
    a different tenant) at the HTTP boundary — see `problem.py`.
    """

    error_code = "saena.not_found.blob_denied"
    status_code = 404


class OpaqueBlobRefError(ArtifactRegistryError):
    """A supplied `blob_ref` is not a well-formed opaque
    `blob:<tenant_id>:<sha256>` reference (never a URL, never a storage
    coordinate — single-gateway invariant)."""

    error_code = "saena.validation.blob_ref_malformed"
    status_code = 400


__all__ = [
    "ArtifactNotFoundError",
    "ArtifactRegistryError",
    "BlobGatewayDeniedError",
    "DuplicateArtifactConflictError",
    "InvalidUriFieldError",
    "OpaqueBlobRefError",
]

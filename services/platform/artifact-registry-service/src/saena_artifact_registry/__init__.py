"""saena_artifact_registry — artifact-registry-service (W2B).

Blob single gateway + immutable `PatchArtifact` manifests. See
`services/platform/artifact-registry-service/README.md` and `app.create_app`
for the FastAPI wiring, `blobstore` for the blob single-gateway invariant,
and `errors`/`problem` for the RFC 9457 (ADR-0015) error mapping.
"""

from __future__ import annotations

from saena_artifact_registry.app import create_app
from saena_artifact_registry.blobstore import (
    BlobRef,
    BlobStore,
    InMemoryBlobStore,
    MinioBlobStore,
    MinioClientConfig,
    parse_blob_ref,
)
from saena_artifact_registry.errors import (
    ArtifactNotFoundError,
    ArtifactRegistryError,
    BlobGatewayDeniedError,
    DuplicateArtifactConflictError,
    InvalidUriFieldError,
    OpaqueBlobRefError,
)

__all__ = [
    "ArtifactNotFoundError",
    "ArtifactRegistryError",
    "BlobGatewayDeniedError",
    "BlobRef",
    "BlobStore",
    "DuplicateArtifactConflictError",
    "InMemoryBlobStore",
    "InvalidUriFieldError",
    "MinioBlobStore",
    "MinioClientConfig",
    "OpaqueBlobRefError",
    "create_app",
    "parse_blob_ref",
]

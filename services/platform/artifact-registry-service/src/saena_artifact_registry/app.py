"""FastAPI app factory for `artifact-registry-service` (W2B exit criterion).

Spec basis: `services/platform/artifact-registry-service/README.md`
("Owned data: object manifest"), `docs/architecture/implementation-waves.md`
W2B exit ("blob 단일 관문 검증" / bypass-blocked, "manifest 불변성"),
`docs/architecture/data-ownership.md` ("manifest = artifact-registry, blob
쓰기 단일 관문 = artifact-registry"), `docs/architecture/contract-catalog.md`
PatchArtifact row (idempotency key `patch_unit_id+worktree_commit`,
customer-proprietary MAX sensitivity — "diff=소스"), ADR-0024(f) (uri fields
reject `?`/`#`), ADR-0007 (tenant path prefix), ADR-0014 (tenant
propagation / `X-Saena-Tenant-Id` header reconciliation), ADR-0015 (RFC 9457
error format).

Three routes:

- `POST /v1/artifacts` — register a `PatchArtifact` manifest + upload its
  blob content in one call. The server, NEVER the client, computes
  `artifact_hash` from the uploaded bytes (single-gateway invariant: a
  client cannot assert a hash that does not match what was actually
  stored). Put-once by `(patch_unit_id, worktree_commit)`
  (`ArtifactManifestPort` semantics): identical resubmission is idempotent
  (200), a conflicting resubmission is 409.
- `GET /v1/artifacts/{patch_unit_id}/{worktree_commit}` — manifest lookup.
  The returned manifest's `artifact_uri`/`manifest_uri` are this service's
  own OPAQUE `blob://<tenant_id>/<sha256>` scheme (ADR-0024f-compliant,
  never a resolvable storage URL/presigned token) — see
  `blobstore.BlobRef`.
- `GET /v1/artifacts/{patch_unit_id}/{worktree_commit}/blob` — gated blob
  fetch, tenant-checked via `blobstore.BlobStore.get_blob`.
"""

from __future__ import annotations

import base64
from typing import Annotated, Any

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from saena_domain.identity import TenantId as DomainTenantId
from saena_domain.identity.errors import InvalidTenantIdError
from saena_domain.identity.http import TENANT_HEADER_NAME
from saena_domain.persistence import (
    ArtifactManifestPort,
    DuplicateManifestError,
    NotFoundError,
    TenantIsolationError,
)
from saena_observability.logging import get_logger
from saena_schemas.domain.patch_artifact_v1 import PatchArtifact

from saena_artifact_registry.blobstore import BlobRef, BlobStore, parse_blob_ref
from saena_artifact_registry.errors import (
    ArtifactNotFoundError,
    ArtifactRegistryError,
    BlobGatewayDeniedError,
    DuplicateArtifactConflictError,
)
from saena_artifact_registry.problem import artifact_registry_error_handler
from saena_artifact_registry.uri_validation import validate_uri_fields

_logger = get_logger("saena_artifact_registry")


class ArtifactManifestFields(BaseModel):
    """Client-supplied manifest fields — every `PatchArtifact` field EXCEPT
    `artifact_hash`, which this service computes server-side from the
    uploaded blob content (single-gateway invariant: the client cannot
    assert a hash the server did not itself derive)."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    run_id: str
    patch_unit_id: Annotated[str, Field(min_length=1)]
    worktree_commit: Annotated[str, Field(pattern="^[0-9a-f]{7,40}$")]
    base_commit: Annotated[str, Field(pattern="^[0-9a-f]{40}$")]
    changed_files: Annotated[list[str], Field(min_length=1)]
    quality_gate_ids: Annotated[list[str], Field(min_length=1)]
    evidence_ids: Annotated[list[str], Field(min_length=1)]
    contract_hash: Annotated[str, Field(pattern="^sha256:[0-9a-f]{64}$")]
    rollback_ref: Annotated[str, Field(min_length=1)]
    created_at: str


class RegisterArtifactRequest(BaseModel):
    """`POST /v1/artifacts` request body — manifest fields + base64 blob."""

    model_config = ConfigDict(extra="forbid")

    manifest: ArtifactManifestFields
    blob_base64: str


class RegisterArtifactResponse(BaseModel):
    """`POST /v1/artifacts` response — the stored manifest only.

    Never a storage URL/presigned token: `artifact_uri`/`manifest_uri` are
    this service's own opaque `blob://<tenant_id>/<sha256>` reference
    scheme (single-gateway invariant)."""

    model_config = ConfigDict(extra="forbid")

    manifest: dict[str, Any]


def _blob_scheme_uri(blob_ref: BlobRef) -> str:
    """Render `blob_ref` as an ADR-0024(f)-compliant opaque uri
    (`blob://<tenant_id>/<sha256>`) — satisfies `UriRef`'s
    `^[a-z0-9+.-]+://[^?#]+$` pattern while remaining a reference-only,
    non-resolvable-by-a-client identifier (never a direct storage
    URL/presigned token)."""
    return f"blob://{blob_ref.tenant_id}/{blob_ref.sha256_hex}"


def _parse_blob_scheme_uri(uri: str) -> BlobRef:
    """Inverse of `_blob_scheme_uri`: parse `blob://<tenant_id>/<sha256>`
    back into a `BlobRef`, by way of the shared opaque-reference parser
    (`blobstore.parse_blob_ref`, `blob:<tenant_id>:<sha256>` form)."""
    body = uri.removeprefix("blob://")
    tenant_id, _, sha256_hex = body.partition("/")
    return parse_blob_ref(f"blob:{tenant_id}:{sha256_hex}")


def _resolve_tenant_id(request: Request) -> str:
    header_value = request.headers.get(TENANT_HEADER_NAME)
    if not header_value:
        raise InvalidTenantIdError(
            f"{TENANT_HEADER_NAME} header is required",
            context={"header_name": TENANT_HEADER_NAME},
        )
    # Validates the ADR-0014 slug pattern; raises InvalidTenantIdError (400
    # via the identity-error handler below) for a malformed tenant_id.
    DomainTenantId(header_value)
    return header_value


def create_app(manifests: ArtifactManifestPort, blobs: BlobStore) -> FastAPI:
    """Build the `artifact-registry-service` FastAPI app.

    `manifests`/`blobs` are injected ports — this factory wires no concrete
    adapter itself (callers pass `InMemoryArtifactManifestStore`/
    `InMemoryBlobStore` for tests, or SQL/MinIO adapters in a real
    deployment bootstrap, out of this patch unit's scope).
    """
    app = FastAPI(title="artifact-registry-service")

    @app.middleware("http")
    async def _tenant_context_middleware(request: Request, call_next: Any) -> Response:
        try:
            tenant_id = _resolve_tenant_id(request)
        except InvalidTenantIdError as exc:
            mapped = ArtifactRegistryError(str(exc), context=exc.context)
            mapped.error_code = "saena.validation.tenant_id_invalid"
            mapped.status_code = 400
            return await artifact_registry_error_handler(request, mapped)
        request.state.tenant_id = tenant_id
        return await call_next(request)

    app.add_exception_handler(ArtifactRegistryError, artifact_registry_error_handler)

    @app.post("/v1/artifacts", status_code=201)
    async def register_artifact(request: Request, body: RegisterArtifactRequest) -> Response:
        tenant_id: str = request.state.tenant_id
        if body.manifest.tenant_id != tenant_id:
            raise ArtifactNotFoundError(
                "manifest tenant_id does not match the authenticated tenant",
                context={"requested_tenant_id": tenant_id},
            )

        try:
            blob_bytes = base64.b64decode(body.blob_base64, validate=True)
        except Exception as exc:  # noqa: BLE001 — malformed client input, not an adapter failure
            error = ArtifactRegistryError(
                "blob_base64 is not valid base64", context={"tenant_id": tenant_id}
            )
            error.error_code = "saena.validation.blob_encoding_invalid"
            error.status_code = 400
            raise error from exc

        blob_ref = blobs.put_blob(tenant_id, blob_bytes)

        manifest_dict: dict[str, Any] = {
            **body.manifest.model_dump(),
            "artifact_uri": _blob_scheme_uri(blob_ref),
            "artifact_hash": f"sha256:{blob_ref.sha256_hex}",
            # manifest_uri references THIS manifest record itself (the
            # ArtifactManifestPort entry keyed by patch_unit_id+worktree_commit),
            # distinct from artifact_uri (the diff/patch blob) — same opaque,
            # non-resolvable-by-a-client scheme, never a direct storage URL.
            "manifest_uri": (
                f"manifest://{tenant_id}/{body.manifest.patch_unit_id}/{body.manifest.worktree_commit}"
            ),
        }

        # Structural validation ahead of storage: full PatchArtifact contract
        # shape (raises pydantic ValidationError -> mapped to 400 below), plus
        # defense-in-depth ADR-0024(f) walk over the whole manifest dict.
        PatchArtifact.model_validate(manifest_dict)
        validate_uri_fields(manifest_dict)

        # Determine fresh-insert vs. idempotent-replay BEFORE calling put():
        # ArtifactManifestPort.put always returns a deep copy equal to what
        # was just stored (fresh write or replay alike), so `stored ==
        # manifest_dict` cannot distinguish the two cases on its own — see
        # ports.py's `put` docstring ("the two are guaranteed equal in that
        # case"). A pre-put existence check is the only reliable signal.
        try:
            manifests.get(
                DomainTenantId(tenant_id),
                body.manifest.patch_unit_id,
                body.manifest.worktree_commit,
            )
            already_existed = True
        except NotFoundError:
            already_existed = False
        except TenantIsolationError as exc:
            raise ArtifactNotFoundError(str(exc), context=exc.context) from exc

        try:
            stored = manifests.put(
                DomainTenantId(tenant_id),
                body.manifest.patch_unit_id,
                body.manifest.worktree_commit,
                manifest_dict,
            )
        except DuplicateManifestError as exc:
            error = DuplicateArtifactConflictError(str(exc), context=exc.context)
            raise error from exc
        except TenantIsolationError as exc:
            raise ArtifactNotFoundError(str(exc), context=exc.context) from exc

        _logger.info(
            "artifact manifest registered",
            extra={
                "saena_attributes": {
                    "saena.tenant_id": tenant_id,
                    "artifact_registry.patch_unit_id": body.manifest.patch_unit_id,
                    "artifact_registry.worktree_commit": body.manifest.worktree_commit,
                    "artifact_registry.blob_sha256": blob_ref.sha256_hex,
                    "artifact_registry.blob_size_bytes": len(blob_bytes),
                }
            },
        )

        status_code = 200 if already_existed else 201
        return Response(
            content=RegisterArtifactResponse(manifest=stored).model_dump_json(),
            status_code=status_code,
            media_type="application/json",
        )

    @app.get("/v1/artifacts/{patch_unit_id}/{worktree_commit}")
    async def get_artifact_manifest(
        request: Request, patch_unit_id: str, worktree_commit: str
    ) -> RegisterArtifactResponse:
        tenant_id: str = request.state.tenant_id
        try:
            manifest = manifests.get(DomainTenantId(tenant_id), patch_unit_id, worktree_commit)
        except NotFoundError as exc:
            raise ArtifactNotFoundError(str(exc), context=exc.context) from exc
        except TenantIsolationError as exc:
            raise ArtifactNotFoundError(str(exc), context=exc.context) from exc
        return RegisterArtifactResponse(manifest=manifest)

    @app.get("/v1/artifacts/{patch_unit_id}/{worktree_commit}/blob")
    async def get_artifact_blob(
        request: Request, patch_unit_id: str, worktree_commit: str
    ) -> Response:
        tenant_id: str = request.state.tenant_id
        try:
            manifest = manifests.get(DomainTenantId(tenant_id), patch_unit_id, worktree_commit)
        except NotFoundError as exc:
            raise ArtifactNotFoundError(str(exc), context=exc.context) from exc
        except TenantIsolationError as exc:
            raise ArtifactNotFoundError(str(exc), context=exc.context) from exc

        blob_ref = _parse_blob_scheme_uri(str(manifest["artifact_uri"]))

        try:
            data = blobs.get_blob(tenant_id, blob_ref)
        except BlobGatewayDeniedError as exc:
            raise ArtifactNotFoundError(str(exc), context=exc.context) from exc

        _logger.info(
            "artifact blob fetched",
            extra={
                "saena_attributes": {
                    "saena.tenant_id": tenant_id,
                    "artifact_registry.patch_unit_id": patch_unit_id,
                    "artifact_registry.worktree_commit": worktree_commit,
                    "artifact_registry.blob_sha256": blob_ref.sha256_hex,
                    "artifact_registry.blob_size_bytes": len(data),
                }
            },
        )

        return Response(content=data, media_type="application/octet-stream")

    return app


__all__ = [
    "ArtifactManifestFields",
    "RegisterArtifactRequest",
    "RegisterArtifactResponse",
    "create_app",
]

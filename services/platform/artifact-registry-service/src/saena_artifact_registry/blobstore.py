"""Blob single-gateway store (W2B exit "blob 단일 관문 검증").

`BlobStore` is a `typing.Protocol` — no service code, including this
service's own routes (`app.py`), talks to object storage except through
`put_blob`/`get_blob`. The opaque `blob:<tenant_id>:<sha256>` reference
(`BlobRef`) is the ONLY thing that ever leaves this module or crosses the
HTTP boundary: it is never a URL, never a presigned token, and never a raw
storage coordinate (bucket/key) — see `BlobRef.__str__` and
`parse_blob_ref`.

Two adapters ship in this patch unit:

- `InMemoryBlobStore` — pure-Python reference implementation, used by
  every unit test that does not specifically exercise the MinIO adapter.
- `MinioBlobStore` — real MinIO adapter (ADR-0007 "Object storage = tenant
  path prefix"). Constructor takes a `MinioClientConfig` object the CALLER
  builds (e.g. from env vars/a secrets manager) — this module never reads
  an environment variable or a secret itself, and never logs `endpoint`,
  `access_key`, or `secret_key`. Unit-tested here via an injected fake
  `minio.Minio`-shaped client (see
  `tests/unit/svc_artifact_registry/test_minio_blobstore.py`); a real MinIO
  integration test is OPTIONAL and skip-if-unavailable (no docker
  requirement in this patch unit).
"""

from __future__ import annotations

import hashlib
import io
import re
import threading
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol, runtime_checkable

from saena_artifact_registry.errors import BlobGatewayDeniedError, OpaqueBlobRefError

#: ADR-0014 tenant slug shape — lowercase alnum + internal hyphens only, no
#: `/`, `.`, or any other separator. Reused by `_BLOB_REF_PATTERN` (opaque
#: reference parsing) AND by `MinioBlobStore._object_name` (path-traversal
#: guard, critic SHOULD-FIX 2, w2-16 review) — a single source of truth for
#: "what a valid tenant_id looks like" in this module.
_TENANT_ID_SEGMENT = r"[a-z0-9]([a-z0-9-]{1,30}[a-z0-9])"
_TENANT_ID_PATTERN = re.compile(rf"^{_TENANT_ID_SEGMENT}$")
_BLOB_REF_PATTERN = re.compile(
    rf"^blob:(?P<tenant_id>{_TENANT_ID_SEGMENT}):(?P<sha256_hex>[0-9a-f]{{64}})$"
)


@dataclass(frozen=True, slots=True)
class BlobRef:
    """Opaque internal blob reference — NEVER a URL.

    `str(ref)` renders `blob:<tenant_id>:<sha256_hex>` — no scheme, no
    host, no query string, no fragment. This is the single-gateway
    invariant's structural guarantee: nothing about this string is
    resolvable directly against object storage by a client, it is only
    meaningful as a lookup key passed back into `BlobStore.get_blob` (or,
    at the HTTP boundary, the gated `GET .../blob` route).
    """

    tenant_id: str
    sha256_hex: str

    def __str__(self) -> str:
        return f"blob:{self.tenant_id}:{self.sha256_hex}"


def parse_blob_ref(value: str) -> BlobRef:
    """Parse an opaque `blob:<tenant_id>:<sha256>` string into a `BlobRef`.

    Raises `OpaqueBlobRefError` (400) if `value` is not a well-formed opaque
    reference — in particular, anything URL-shaped (containing `://`, `?`,
    or `#`) is rejected here, never silently accepted.
    """
    match = _BLOB_REF_PATTERN.match(value)
    if match is None:
        raise OpaqueBlobRefError(
            f"blob_ref {value!r} is not a well-formed opaque blob:<tenant_id>:<sha256> reference",
            context={"blob_ref": value},
        )
    return BlobRef(tenant_id=match.group("tenant_id"), sha256_hex=match.group("sha256_hex"))


def compute_sha256(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of `data`."""
    return hashlib.sha256(data).hexdigest()


@runtime_checkable
class BlobStore(Protocol):
    """Blob content store Protocol — the single gateway to object storage.

    Both methods are TENANT-SCOPED: `tenant_id` is always the first
    argument, and `get_blob` MUST verify the requested blob actually
    belongs to `tenant_id` before returning content — a mismatch raises
    `BlobGatewayDeniedError`, never a bare "not found" that would let a
    caller distinguish "wrong tenant" from "never existed" (same
    fail-closed shape as `saena_domain.persistence.errors.
    TenantIsolationError`).
    """

    def put_blob(self, tenant_id: str, data: bytes) -> BlobRef:
        """Store `data` under `tenant_id`, content-addressed by its SHA-256.

        Returns the opaque `BlobRef` (never a URL/presigned token).
        Idempotent: storing identical bytes twice for the same tenant
        returns an equal `BlobRef` and does not duplicate storage work
        observably (adapters MAY re-upload; callers only observe the
        returned reference and successful completion).
        """
        ...

    def get_blob(self, tenant_id: str, blob_ref: BlobRef) -> bytes:
        """Return the stored bytes for `blob_ref`, gated by `tenant_id`.

        Raises `BlobGatewayDeniedError` if `blob_ref.tenant_id != tenant_id`
        (cross-tenant bypass attempt) OR if no blob exists under that
        tenant/hash at all — both cases are indistinguishable to the
        caller, by design (never leak existence across tenants).
        """
        ...


class InMemoryBlobStore:
    """Pure-Python reference `BlobStore` — content-addressed, tenant-scoped
    dict of dicts, guarded by a lock (mirrors
    `saena_domain.persistence.memory` adapter conventions)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, dict[str, bytes]] = {}

    def put_blob(self, tenant_id: str, data: bytes) -> BlobRef:
        sha256_hex = compute_sha256(data)
        with self._lock:
            tenant_store = self._store.setdefault(tenant_id, {})
            tenant_store[sha256_hex] = bytes(data)
        return BlobRef(tenant_id=tenant_id, sha256_hex=sha256_hex)

    def get_blob(self, tenant_id: str, blob_ref: BlobRef) -> bytes:
        if blob_ref.tenant_id != tenant_id:
            raise BlobGatewayDeniedError(
                "blob_ref belongs to a different tenant",
                context={"requested_tenant_id": tenant_id},
            )
        with self._lock:
            data = self._store.get(tenant_id, {}).get(blob_ref.sha256_hex)
        if data is None:
            raise BlobGatewayDeniedError(
                "no blob stored for this tenant/hash",
                context={"requested_tenant_id": tenant_id},
            )
        return data


@dataclass(frozen=True, slots=True)
class MinioClientConfig:
    """Injected MinIO connection configuration.

    This module NEVER reads secrets/env vars itself — the caller (services
    bootstrap / k3s Deployment env wiring, out of this patch unit's scope)
    is responsible for sourcing `endpoint`/`access_key`/`secret_key` from a
    secrets manager or pod env and constructing this object. Never logged:
    `MinioBlobStore` only ever logs `bucket`/tenant/hash/size, never these
    fields (see `MinioBlobStore` docstring and
    `tests/unit/svc_artifact_registry/test_minio_blobstore.py::
    test_minio_adapter_never_logs_credentials`).
    """

    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool = True


@runtime_checkable
class _MinioClientLike(Protocol):
    """Structural subset of `minio.Minio` this adapter calls — lets tests
    inject a fake client without depending on real network I/O or a live
    MinIO instance."""

    def bucket_exists(self, bucket_name: str) -> bool: ...

    def make_bucket(self, bucket_name: str) -> None: ...

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> Any: ...

    def get_object(self, bucket_name: str, object_name: str) -> Any: ...

    def stat_object(self, bucket_name: str, object_name: str) -> Any: ...


class MinioBlobStore:
    """Real MinIO-backed `BlobStore` (ADR-0007 "Object storage = tenant
    path prefix").

    Object key layout: `<tenant_id>/<sha256_hex>` — the tenant path prefix
    IS the tenant isolation boundary at the storage layer (ADR-0007), on
    top of (not instead of) this adapter's own `tenant_id` gate check on
    `get_blob`. `client` is any object satisfying `_MinioClientLike` — in
    production this is a real `minio.Minio(...)` instance built by the
    caller from a `MinioClientConfig`; in tests it is an injected fake
    (see `tests/unit/svc_artifact_registry/test_minio_blobstore.py`), so
    this adapter is fully unit-testable without a running MinIO server. A
    real-MinIO integration test is OPTIONAL and skip-if-unavailable — not
    required by this patch unit.
    """

    def __init__(self, client: _MinioClientLike, config: MinioClientConfig) -> None:
        self._client = client
        self._bucket = config.bucket
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    @staticmethod
    def _object_name(tenant_id: str, sha256_hex: str) -> str:
        """Build the ADR-0007 tenant-path-prefixed object key.

        Independently validates `tenant_id` against the ADR-0014 slug shape
        BEFORE it is interpolated into an object key — never trusts the
        HTTP layer's own validation alone (critic SHOULD-FIX 2, w2-16
        review): a `tenant_id` containing `/` or `..` could otherwise let a
        caller escape the intended `<tenant_id>/<sha256>` prefix and write
        to or read from an arbitrary key in the bucket (path traversal).
        Raises `OpaqueBlobRefError` (400) on a malformed `tenant_id` — same
        error type `parse_blob_ref` raises for a malformed opaque
        reference, since both are "this identifier does not have the shape
        this module requires" failures.
        """
        if not _TENANT_ID_PATTERN.match(tenant_id):
            raise OpaqueBlobRefError(
                f"tenant_id {tenant_id!r} does not match the required ADR-0014 slug "
                "shape — refusing to build an object storage key from it",
                context={"tenant_id": tenant_id},
            )
        return f"{tenant_id}/{sha256_hex}"

    def put_blob(self, tenant_id: str, data: bytes) -> BlobRef:
        sha256_hex = compute_sha256(data)
        object_name = self._object_name(tenant_id, sha256_hex)
        self._client.put_object(
            self._bucket,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type="application/octet-stream",
        )
        return BlobRef(tenant_id=tenant_id, sha256_hex=sha256_hex)

    def get_blob(self, tenant_id: str, blob_ref: BlobRef) -> bytes:
        if blob_ref.tenant_id != tenant_id:
            raise BlobGatewayDeniedError(
                "blob_ref belongs to a different tenant",
                context={"requested_tenant_id": tenant_id},
            )
        object_name = self._object_name(tenant_id, blob_ref.sha256_hex)
        try:
            response = self._client.get_object(self._bucket, object_name)
        except Exception as exc:  # noqa: BLE001 — adapter boundary: any client
            # failure (including a real minio.error.S3Error "NoSuchKey") maps
            # to the same fail-closed BlobGatewayDeniedError as a cross-tenant
            # attempt, never leaking storage-layer diagnostics.
            raise BlobGatewayDeniedError(
                "no blob stored for this tenant/hash",
                context={"requested_tenant_id": tenant_id},
            ) from exc
        try:
            return bytes(response.read())
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
            release = getattr(response, "release_conn", None)
            if callable(release):
                release()


__all__ = [
    "BlobRef",
    "BlobStore",
    "InMemoryBlobStore",
    "MinioBlobStore",
    "MinioClientConfig",
    "compute_sha256",
    "parse_blob_ref",
]

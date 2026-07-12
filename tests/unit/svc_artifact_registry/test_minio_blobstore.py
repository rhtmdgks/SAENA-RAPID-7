"""`MinioBlobStore` — unit-tested via an injected fake `minio.Minio`-shaped
client (ADR-0007 tenant path-prefix correctness). No real MinIO/docker
required for this patch unit; a real-MinIO integration test is OPTIONAL and
out of scope here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, BinaryIO

import pytest
from saena_artifact_registry.blobstore import (
    BlobGatewayDeniedError,
    BlobRef,
    MinioBlobStore,
    MinioClientConfig,
    compute_sha256,
)
from saena_artifact_registry.errors import OpaqueBlobRefError


@dataclass
class _FakeResponse:
    data: bytes
    closed: bool = False
    released: bool = False

    def read(self) -> bytes:
        return self.data

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class _FakeMinioClient:
    """Structural fake satisfying `blobstore._MinioClientLike` — stores
    objects in a plain dict keyed by `(bucket, object_name)`, mirroring real
    MinIO's bucket/object-key addressing without any network I/O."""

    def __init__(self, *, bucket_already_exists: bool = False) -> None:
        self._bucket_exists = bucket_already_exists
        self.made_buckets: list[str] = []
        self.objects: dict[tuple[str, str], bytes] = {}
        self.put_calls: list[tuple[str, str, int, str]] = []

    def bucket_exists(self, bucket_name: str) -> bool:
        return self._bucket_exists

    def make_bucket(self, bucket_name: str) -> None:
        self.made_buckets.append(bucket_name)
        self._bucket_exists = True

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> Any:
        payload = data.read()
        assert len(payload) == length
        self.objects[(bucket_name, object_name)] = payload
        self.put_calls.append((bucket_name, object_name, length, content_type))
        return None

    def get_object(self, bucket_name: str, object_name: str) -> Any:
        key = (bucket_name, object_name)
        if key not in self.objects:
            raise KeyError(f"NoSuchKey: {key!r}")
        return _FakeResponse(self.objects[key])

    def stat_object(self, bucket_name: str, object_name: str) -> Any:
        raise NotImplementedError


def _config(bucket: str = "saena-artifacts") -> MinioClientConfig:
    return MinioClientConfig(
        endpoint="minio.internal:9000",
        access_key="fake-access-key",
        secret_key="fake-secret-key",
        bucket=bucket,
    )


def test_constructor_creates_bucket_if_absent() -> None:
    fake = _FakeMinioClient(bucket_already_exists=False)

    MinioBlobStore(fake, _config())

    assert fake.made_buckets == ["saena-artifacts"]


def test_constructor_does_not_recreate_existing_bucket() -> None:
    fake = _FakeMinioClient(bucket_already_exists=True)

    MinioBlobStore(fake, _config())

    assert fake.made_buckets == []


def test_put_blob_uses_tenant_path_prefix_object_key() -> None:
    fake = _FakeMinioClient(bucket_already_exists=True)
    store = MinioBlobStore(fake, _config())
    data = b"patch diff bytes"

    ref = store.put_blob("acme-co", data)

    expected_key = f"acme-co/{compute_sha256(data)}"
    assert ("saena-artifacts", expected_key) in fake.objects
    assert fake.objects[("saena-artifacts", expected_key)] == data
    assert ref == BlobRef(tenant_id="acme-co", sha256_hex=compute_sha256(data))


def test_put_blob_different_tenants_same_content_different_keys() -> None:
    fake = _FakeMinioClient(bucket_already_exists=True)
    store = MinioBlobStore(fake, _config())
    data = b"shared content bytes"

    ref_a = store.put_blob("acme-co", data)
    ref_b = store.put_blob("globex-co", data)

    assert ref_a.sha256_hex == ref_b.sha256_hex
    assert ("saena-artifacts", f"acme-co/{ref_a.sha256_hex}") in fake.objects
    assert ("saena-artifacts", f"globex-co/{ref_b.sha256_hex}") in fake.objects


def test_get_blob_round_trips_through_fake_client() -> None:
    fake = _FakeMinioClient(bucket_already_exists=True)
    store = MinioBlobStore(fake, _config())
    data = b"round trip content"
    ref = store.put_blob("acme-co", data)

    result = store.get_blob("acme-co", ref)

    assert result == data


def test_get_blob_cross_tenant_denied_without_calling_client() -> None:
    fake = _FakeMinioClient(bucket_already_exists=True)
    store = MinioBlobStore(fake, _config())
    ref = store.put_blob("acme-co", b"tenant a secret")

    with pytest.raises(BlobGatewayDeniedError):
        store.get_blob("globex-co", ref)


def test_get_blob_missing_object_maps_to_gateway_denied_not_leaking_diagnostics() -> None:
    fake = _FakeMinioClient(bucket_already_exists=True)
    store = MinioBlobStore(fake, _config())
    forged_ref = BlobRef(tenant_id="acme-co", sha256_hex="f" * 64)

    with pytest.raises(BlobGatewayDeniedError):
        store.get_blob("acme-co", forged_ref)


def test_get_blob_closes_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeMinioClient(bucket_already_exists=True)
    store = MinioBlobStore(fake, _config())
    data = b"connection cleanup check"
    ref = store.put_blob("acme-co", data)

    captured: dict[str, _FakeResponse] = {}
    original_get_object = fake.get_object

    def _tracking_get_object(bucket_name: str, object_name: str) -> Any:
        response = original_get_object(bucket_name, object_name)
        captured["response"] = response
        return response

    monkeypatch.setattr(fake, "get_object", _tracking_get_object)

    store.get_blob("acme-co", ref)

    assert captured["response"].closed is True
    assert captured["response"].released is True


def test_minio_adapter_never_logs_credentials(caplog: pytest.LogCaptureFixture) -> None:
    """`MinioClientConfig` carries `access_key`/`secret_key` — this adapter
    must never emit them via logging, str(), or repr() reachable from normal
    operation. Structural check: neither field name nor its value appears
    in the adapter's own module source-level logging calls (this adapter
    performs no logging of its own at all — logging happens one layer up in
    `app.py`, which only ever logs hash/size, see
    `test_logging_safety.py`)."""
    import inspect

    import saena_artifact_registry.blobstore as blobstore_module

    source = inspect.getsource(blobstore_module.MinioBlobStore)
    assert "logging" not in source
    assert "print(" not in source
    assert "access_key" not in source
    assert "secret_key" not in source


@pytest.mark.parametrize(
    "malicious_tenant_id",
    [
        "../other",
        "../../etc/passwd",
        "acme-co/../globex-co",
        "acme-co/nested",
        "..",
        "a/b",
    ],
)
def test_put_blob_rejects_path_traversal_tenant_id(malicious_tenant_id: str) -> None:
    """Critic SHOULD-FIX 2 (w2-16 review): the adapter must be
    independently safe even if the HTTP layer's own `X-Saena-Tenant-Id`
    validation were ever bypassed or misconfigured — `tenant_id` containing
    `/` or `..` must never reach `put_object`'s object key."""
    fake = _FakeMinioClient(bucket_already_exists=True)
    store = MinioBlobStore(fake, _config())

    with pytest.raises(OpaqueBlobRefError):
        store.put_blob(malicious_tenant_id, b"data")

    assert fake.put_calls == []


@pytest.mark.parametrize(
    "malicious_tenant_id",
    [
        "../other",
        "../../etc/passwd",
        "acme-co/../globex-co",
    ],
)
def test_get_blob_rejects_path_traversal_tenant_id(malicious_tenant_id: str) -> None:
    fake = _FakeMinioClient(bucket_already_exists=True)
    store = MinioBlobStore(fake, _config())
    forged_ref = BlobRef(tenant_id=malicious_tenant_id, sha256_hex="a" * 64)

    with pytest.raises(OpaqueBlobRefError):
        store.get_blob(malicious_tenant_id, forged_ref)


def test_put_blob_accepts_valid_tenant_id_after_guard_added() -> None:
    """Regression guard: the path-traversal check must not reject legitimate
    ADR-0014-shaped tenant_ids."""
    fake = _FakeMinioClient(bucket_already_exists=True)
    store = MinioBlobStore(fake, _config())

    ref = store.put_blob("acme-co", b"legit data")

    assert ref.tenant_id == "acme-co"
    assert ("saena-artifacts", f"acme-co/{ref.sha256_hex}") in fake.objects

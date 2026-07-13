"""Blob single-gateway invariant: opaque `blob_ref`, no direct storage
URL/presigned token ever leaves the gateway, `InMemoryBlobStore` tenant
gating."""

from __future__ import annotations

import pytest
from saena_artifact_registry.blobstore import (
    BlobRef,
    InMemoryBlobStore,
    compute_sha256,
    parse_blob_ref,
)
from saena_artifact_registry.errors import BlobGatewayDeniedError, OpaqueBlobRefError


def test_blob_ref_str_is_opaque_no_scheme_host() -> None:
    ref = BlobRef(tenant_id="acme-co", sha256_hex="a" * 64)

    rendered = str(ref)

    assert rendered == f"blob:acme-co:{'a' * 64}"
    assert "://" not in rendered
    assert "?" not in rendered
    assert "#" not in rendered


def test_parse_blob_ref_round_trips() -> None:
    ref = BlobRef(tenant_id="acme-co", sha256_hex="b" * 64)

    parsed = parse_blob_ref(str(ref))

    assert parsed == ref


@pytest.mark.parametrize(
    "malformed",
    [
        "https://s3.amazonaws.com/bucket/key?X-Amz-Signature=abc",
        "blob://acme-co/" + "a" * 64,  # wrong separator (:// not opaque form)
        "blob:acme-co:tooshort",
        "not-a-blob-ref-at-all",
        "",
    ],
)
def test_parse_blob_ref_rejects_url_shaped_or_malformed_values(malformed: str) -> None:
    with pytest.raises(OpaqueBlobRefError):
        parse_blob_ref(malformed)


def test_put_blob_then_get_blob_round_trips() -> None:
    store = InMemoryBlobStore()
    data = b"artifact bytes"

    ref = store.put_blob("acme-co", data)

    assert ref.sha256_hex == compute_sha256(data)
    assert store.get_blob("acme-co", ref) == data


def test_get_blob_cross_tenant_denied() -> None:
    store = InMemoryBlobStore()
    ref = store.put_blob("acme-co", b"secret diff")

    with pytest.raises(BlobGatewayDeniedError):
        store.get_blob("globex-co", ref)


def test_get_blob_constructed_ref_for_nonexistent_hash_denied() -> None:
    """Bypass test: constructing another tenant's (or a never-stored)
    `blob_ref` directly must not succeed — same-tenant, wrong hash."""
    store = InMemoryBlobStore()
    store.put_blob("acme-co", b"real content")
    forged_ref = BlobRef(tenant_id="acme-co", sha256_hex="f" * 64)

    with pytest.raises(BlobGatewayDeniedError):
        store.get_blob("acme-co", forged_ref)

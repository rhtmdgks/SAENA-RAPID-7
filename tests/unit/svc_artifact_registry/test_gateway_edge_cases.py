"""Edge-case branches not reachable through the "obvious" happy/bypass
paths — data-integrity scenarios where the manifest store and blob store
have diverged (e.g. a manifest was registered but its referenced blob was
independently removed from the blob store)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from registry_factories import build_register_request
from saena_artifact_registry.blobstore import InMemoryBlobStore
from saena_domain.persistence import InMemoryArtifactManifestStore


def test_blob_fetch_denied_when_blob_missing_despite_manifest_present(
    client: TestClient,
    tenant_headers: dict[str, str],
    manifests: InMemoryArtifactManifestStore,
    blobs: InMemoryBlobStore,
) -> None:
    """Manifest exists (registered normally), but its blob has since been
    removed from the blob store directly (bypassing this service) —
    `get_artifact_blob` must map `BlobGatewayDeniedError` to 404, not leak a
    500 or raw storage-layer diagnostics."""
    client.post("/v1/artifacts", json=build_register_request(), headers=tenant_headers)

    # Simulate the blob having vanished from storage independently of the
    # manifest (blobs._store is this test-only in-memory adapter's own
    # internal dict — clearing it does not go through the single gateway,
    # exactly the divergence scenario this test targets).
    blobs._store.clear()  # type: ignore[attr-defined]

    response = client.get(
        "/v1/artifacts/w2-16-artifact-registry/9f1c2e7/blob", headers=tenant_headers
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "saena.not_found.artifact_manifest"

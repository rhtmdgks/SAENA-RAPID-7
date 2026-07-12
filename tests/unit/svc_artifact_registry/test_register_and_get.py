"""`POST /v1/artifacts` + `GET /v1/artifacts/{...}` — register/get happy
path, sha256 correctness, idempotent replay, duplicate-content conflict."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
from registry_factories import build_register_request


def test_register_artifact_happy_path_returns_201(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    response = client.post("/v1/artifacts", json=build_register_request(), headers=tenant_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["manifest"]["patch_unit_id"] == "w2-16-artifact-registry"
    assert body["manifest"]["worktree_commit"] == "9f1c2e7"


def test_register_artifact_computes_correct_sha256(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    blob = b"exact bytes to hash"
    expected = hashlib.sha256(blob).hexdigest()

    response = client.post(
        "/v1/artifacts",
        json=build_register_request(blob=blob),
        headers=tenant_headers,
    )

    assert response.status_code == 201
    manifest = response.json()["manifest"]
    assert manifest["artifact_hash"] == f"sha256:{expected}"


def test_register_then_get_round_trips_manifest(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    client.post("/v1/artifacts", json=build_register_request(), headers=tenant_headers)

    response = client.get("/v1/artifacts/w2-16-artifact-registry/9f1c2e7", headers=tenant_headers)

    assert response.status_code == 200
    assert response.json()["manifest"]["patch_unit_id"] == "w2-16-artifact-registry"


def test_register_duplicate_same_content_is_idempotent_200(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    request_body = build_register_request()

    first = client.post("/v1/artifacts", json=request_body, headers=tenant_headers)
    second = client.post("/v1/artifacts", json=request_body, headers=tenant_headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json() == second.json()


def test_register_duplicate_different_content_returns_409(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    client.post(
        "/v1/artifacts",
        json=build_register_request(blob=b"first version"),
        headers=tenant_headers,
    )

    response = client.post(
        "/v1/artifacts",
        json=build_register_request(blob=b"second, different version"),
        headers=tenant_headers,
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "saena.conflict.duplicate_artifact_manifest"


def test_get_missing_artifact_returns_404(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    response = client.get("/v1/artifacts/never-registered/deadbeef", headers=tenant_headers)

    assert response.status_code == 404
    assert response.json()["error_code"] == "saena.not_found.artifact_manifest"


def test_manifest_response_has_no_storage_url(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    """The manifest's uri fields must be this service's own opaque scheme,
    never a resolvable S3/MinIO storage URL/presigned token."""
    response = client.post("/v1/artifacts", json=build_register_request(), headers=tenant_headers)

    manifest = response.json()["manifest"]
    for field in ("artifact_uri", "manifest_uri"):
        value = manifest[field]
        assert "?" not in value
        assert "#" not in value
        assert "s3." not in value
        assert "minio" not in value.lower() or value.startswith(("blob://", "manifest://"))
        assert "X-Amz" not in value

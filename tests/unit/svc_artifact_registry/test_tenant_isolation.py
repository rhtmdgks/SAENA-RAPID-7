"""Cross-tenant bypass tests — W2B exit "blob 단일 관문 검증" (bypass-blocked)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from registry_factories import TENANT_B, build_register_request
from saena_domain.identity.http import TENANT_HEADER_NAME


def test_cross_tenant_manifest_get_is_denied(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    client.post("/v1/artifacts", json=build_register_request(), headers=tenant_headers)

    response = client.get(
        "/v1/artifacts/w2-16-artifact-registry/9f1c2e7",
        headers={TENANT_HEADER_NAME: TENANT_B},
    )

    assert response.status_code in (403, 404)


def test_cross_tenant_blob_fetch_is_denied(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    client.post("/v1/artifacts", json=build_register_request(), headers=tenant_headers)

    response = client.get(
        "/v1/artifacts/w2-16-artifact-registry/9f1c2e7/blob",
        headers={TENANT_HEADER_NAME: TENANT_B},
    )

    assert response.status_code in (403, 404)


def test_manifest_tenant_mismatch_with_header_is_denied(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    """A caller authenticated as TENANT_A cannot register a manifest whose
    own `manifest.tenant_id` field claims TENANT_B."""
    request_body = build_register_request(manifest_overrides={"tenant_id": "globex-co"})

    response = client.post("/v1/artifacts", json=request_body, headers=tenant_headers)

    assert response.status_code in (400, 403, 404)


def test_missing_tenant_header_is_rejected(client: TestClient) -> None:
    response = client.get("/v1/artifacts/some-unit/deadbeef")

    assert response.status_code == 400


def test_malformed_tenant_header_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/v1/artifacts/some-unit/deadbeef", headers={TENANT_HEADER_NAME: "NOT_VALID_$$"}
    )

    assert response.status_code == 400


def test_get_blob_via_gateway_after_register_succeeds(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    blob = b"the actual diff content"
    client.post("/v1/artifacts", json=build_register_request(blob=blob), headers=tenant_headers)

    response = client.get(
        "/v1/artifacts/w2-16-artifact-registry/9f1c2e7/blob", headers=tenant_headers
    )

    assert response.status_code == 200
    assert response.content == blob


def test_register_artifact_with_malformed_base64_returns_400(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    request_body = build_register_request()
    request_body["blob_base64"] = "not-valid-base64-!!!@@@"

    response = client.post("/v1/artifacts", json=request_body, headers=tenant_headers)

    assert response.status_code == 400
    assert response.json()["error_code"] == "saena.validation.blob_encoding_invalid"


def test_get_missing_blob_manifest_returns_404(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    response = client.get("/v1/artifacts/never-registered/deadbeef/blob", headers=tenant_headers)

    assert response.status_code == 404
    assert response.json()["error_code"] == "saena.not_found.artifact_manifest"


def test_cross_tenant_register_pre_existence_check_raises_tenant_isolation(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    """Registering under TENANT_A, then TENANT_B attempting to register the
    SAME `(patch_unit_id, worktree_commit)` key exercises both the
    pre-`put()` existence-check `TenantIsolationError` branch and the
    `put()`-call `TenantIsolationError` branch — both denied."""
    client.post("/v1/artifacts", json=build_register_request(), headers=tenant_headers)

    request_body = build_register_request(manifest_overrides={"tenant_id": TENANT_B})
    response = client.post(
        "/v1/artifacts", json=request_body, headers={TENANT_HEADER_NAME: TENANT_B}
    )

    assert response.status_code == 404

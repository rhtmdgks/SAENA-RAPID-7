"""ADR-0024(f) uri-field structural ban — unit tests for
`uri_validation.validate_uri_fields`, and an end-to-end 400 through the
HTTP API when a manifest carries a query-string/fragment uri."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from registry_factories import build_register_request
from saena_artifact_registry.errors import InvalidUriFieldError
from saena_artifact_registry.uri_validation import validate_uri_fields


def test_valid_uri_fields_pass() -> None:
    validate_uri_fields({"artifact_uri": "blob://acme-co/" + "a" * 64})


def test_valid_uri_field_nested_in_dict_passes_and_continues() -> None:
    """A nested dict that validates successfully must not raise — and
    validation must continue past it to sibling keys."""
    validate_uri_fields(
        {
            "nested": {"snapshot_uri": "blob://acme-co/" + "a" * 64},
            "patch_unit_id": "unit-1",
        }
    )


def test_uri_field_with_query_string_rejected() -> None:
    with pytest.raises(InvalidUriFieldError):
        validate_uri_fields({"artifact_uri": "https://s3.example.com/bucket/key?token=abc"})


def test_uri_field_with_fragment_rejected() -> None:
    with pytest.raises(InvalidUriFieldError):
        validate_uri_fields({"manifest_uri": "https://s3.example.com/bucket/key#frag"})


def test_uri_field_missing_scheme_rejected() -> None:
    with pytest.raises(InvalidUriFieldError):
        validate_uri_fields({"artifact_uri": "not-a-uri-at-all"})


def test_uri_field_nested_in_dict_is_validated() -> None:
    with pytest.raises(InvalidUriFieldError):
        validate_uri_fields({"nested": {"snapshot_uri": "bad?query=1"}})


def test_uri_field_nested_in_list_of_dicts_is_validated() -> None:
    with pytest.raises(InvalidUriFieldError):
        validate_uri_fields({"items": [{"report_uri": "https://x/y#frag"}]})


def test_non_uri_fields_are_ignored() -> None:
    validate_uri_fields({"changed_files": ["a.py", "b.py"], "patch_unit_id": "unit-1"})


def test_register_artifact_rejects_extra_uri_shaped_field(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    """`ArtifactManifestFields` is `extra="forbid"` (pydantic) — a client
    cannot smuggle a presigned-token-bearing uri field into the manifest at
    all; FastAPI/pydantic reject it as a 422 before this service's own
    ADR-0024(f) walk ever runs. Confirms the structural-forbid layer is
    itself in place (defense in depth's outer layer)."""
    request_body = build_register_request()
    request_body["manifest"]["snapshot_uri"] = "https://s3.example.com/bucket/key?token=leak"

    response = client.post("/v1/artifacts", json=request_body, headers=tenant_headers)

    assert response.status_code == 422


def test_server_computed_artifact_uri_is_never_client_controlled(
    client: TestClient, tenant_headers: dict[str, str]
) -> None:
    """The client cannot influence `artifact_uri`/`manifest_uri`/
    `artifact_hash` at all — `ArtifactManifestFields` has no such fields, so
    the server-computed opaque scheme is authoritative regardless of what a
    malicious client might try to inject via `blob_base64` framing."""
    request_body = build_register_request()

    response = client.post("/v1/artifacts", json=request_body, headers=tenant_headers)

    manifest = response.json()["manifest"]
    assert "snapshot_uri" not in manifest
    assert manifest["artifact_uri"].startswith("blob://")
    assert manifest["manifest_uri"].startswith("manifest://")

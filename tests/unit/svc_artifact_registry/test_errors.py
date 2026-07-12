"""Unit tests for `saena_artifact_registry.errors.ArtifactRegistryError` and
subclasses — structured `to_dict()` representation, `error_code`/`context`
shape (mirrors `saena_domain.persistence.errors` conventions)."""

from __future__ import annotations

from saena_artifact_registry.errors import (
    ArtifactNotFoundError,
    ArtifactRegistryError,
    BlobGatewayDeniedError,
    DuplicateArtifactConflictError,
    InvalidUriFieldError,
    OpaqueBlobRefError,
)


def test_to_dict_includes_error_code_message_and_context() -> None:
    error = ArtifactRegistryError("something went wrong", context={"key": "value"})

    result = error.to_dict()

    assert result == {
        "error_code": "saena.artifact_registry.error",
        "message": "something went wrong",
        "key": "value",
    }


def test_to_dict_with_no_context_omits_extra_keys() -> None:
    error = ArtifactRegistryError("plain message")

    assert error.to_dict() == {
        "error_code": "saena.artifact_registry.error",
        "message": "plain message",
    }


def test_context_is_defensively_copied() -> None:
    original_context = {"a": 1}
    error = ArtifactRegistryError("msg", context=original_context)

    original_context["a"] = 999

    assert error.context == {"a": 1}


def test_subclass_error_codes_and_status_codes() -> None:
    assert InvalidUriFieldError("x").error_code == "saena.validation.uri_field_invalid"
    assert InvalidUriFieldError("x").status_code == 400
    assert (
        DuplicateArtifactConflictError("x").error_code
        == "saena.conflict.duplicate_artifact_manifest"
    )
    assert DuplicateArtifactConflictError("x").status_code == 409
    assert ArtifactNotFoundError("x").error_code == "saena.not_found.artifact_manifest"
    assert ArtifactNotFoundError("x").status_code == 404
    assert BlobGatewayDeniedError("x").error_code == "saena.not_found.blob_denied"
    assert BlobGatewayDeniedError("x").status_code == 404
    assert OpaqueBlobRefError("x").error_code == "saena.validation.blob_ref_malformed"
    assert OpaqueBlobRefError("x").status_code == 400


def test_subclass_to_dict_uses_own_error_code() -> None:
    error = ArtifactNotFoundError("no such manifest", context={"patch_unit_id": "u1"})

    assert error.to_dict() == {
        "error_code": "saena.not_found.artifact_manifest",
        "message": "no such manifest",
        "patch_unit_id": "u1",
    }

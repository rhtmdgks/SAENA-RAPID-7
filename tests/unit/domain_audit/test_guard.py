"""Tests for saena_domain.audit.guard — forbidden-data categories + non-leaking errors."""

from __future__ import annotations

import pytest
from saena_domain.audit.guard import (
    ERROR_DETAIL_ALLOWED_KEYS,
    ForbiddenAuditDataError,
    guard_actor_fields,
    guard_error_detail,
    guard_payload,
)

SECRET_VALUE = "s3cr3t-value-should-never-appear-in-any-error-message"


# --- credential-ish keys -------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "private_key",
        "credential",
        "bearer_token",
        "db_password",
        "X-Api-Key",
        "Authorization",
    ],
)
def test_guard_payload_rejects_credential_keys(key: str) -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_payload({key: SECRET_VALUE})


def test_guard_payload_rejects_nested_credential_key() -> None:
    with pytest.raises(ForbiddenAuditDataError) as excinfo:
        guard_payload({"user": {"nested": {"api_key": SECRET_VALUE}}})
    assert excinfo.value.key_path == "user.nested.api_key"


def test_guard_payload_allows_actor_id_key() -> None:
    # actor_id contains "id" but must not be caught by any forbidden pattern.
    guard_payload({"actor_id": "user-123"})


# --- stack-trace / raw exception dumps ------------------------------------------------


def test_guard_payload_rejects_traceback_header() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_payload({"summary": "Traceback (most recent call last):\n  ..."})


def test_guard_payload_rejects_exception_frame_dump() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_payload({"detail": 'File "app.py", line 42, in handler'})


def test_guard_payload_allows_ordinary_string_value() -> None:
    guard_payload({"summary": "patch unit completed successfully"})


# --- source-content style keys --------------------------------------------------------


@pytest.mark.parametrize("key", ["diff", "patch", "file_content", "unified_diff", "raw_diff"])
def test_guard_payload_rejects_source_content_keys(key: str) -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_payload({key: "--- a/file\n+++ b/file\n"})


def test_guard_payload_allows_patch_unit_id_identifier_key() -> None:
    # patch_unit_id is a legitimate identifier reference (PatchArtifact
    # idempotency-key component, contract-catalog.md P0 row 10) — its
    # leading token is "patch" but it is not source content.
    guard_payload({"patch_unit_id": "w2-04-audit"})


def test_guard_payload_allows_action_field_containing_patch_token() -> None:
    guard_payload({"action": "patch.unit.completed.v1"})


# --- PII beyond actor_id ---------------------------------------------------------------


@pytest.mark.parametrize("key", ["email", "full_name", "phone"])
def test_guard_payload_rejects_pii_keys(key: str) -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_payload({key: "irrelevant-value"})


def test_guard_payload_rejects_email_pattern_value() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_payload({"note": "user@example.com"})


def test_guard_payload_allows_non_email_string() -> None:
    guard_payload({"note": "not an email at all"})


# --- error-detail shape ------------------------------------------------------------


def test_guard_payload_allows_conformant_error_object() -> None:
    guard_payload(
        {
            "error": {
                "error_code": "saena.internal.unexpected",
                "retryable": False,
                "summary": "unexpected failure",
            }
        }
    )


def test_guard_payload_rejects_error_object_with_excess_field() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_payload(
            {
                "error": {
                    "error_code": "saena.internal.unexpected",
                    "retryable": False,
                    "summary": "unexpected failure",
                    "stack": "some raw diagnostic dump",
                }
            }
        )


def test_guard_error_detail_accepts_allowed_keys_only() -> None:
    guard_error_detail(
        {"error_code": "saena.validation.schema_mismatch", "retryable": False, "summary": "bad"}
    )


def test_guard_error_detail_rejects_extra_key() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_error_detail(
            {
                "error_code": "saena.validation.schema_mismatch",
                "retryable": False,
                "summary": "bad",
                "raw_request": "customer payload dump",
            }
        )


def test_error_detail_allowed_keys_matches_adr_0015_shape() -> None:
    assert (
        frozenset({"error_code", "retryable", "summary", "trace_id"}) == ERROR_DETAIL_ALLOWED_KEYS
    )


# --- lists / nested structures ----------------------------------------------------


def test_guard_payload_walks_lists() -> None:
    with pytest.raises(ForbiddenAuditDataError) as excinfo:
        guard_payload({"items": [{"ok": 1}, {"password": SECRET_VALUE}]})
    assert excinfo.value.key_path == "items[1].password"


def test_guard_payload_accepts_clean_nested_structure() -> None:
    guard_payload(
        {
            "action": "patch.unit.completed.v1",
            "items": [{"unit": "w2-04"}, {"unit": "w2-05"}],
            "counts": {"passed": 3, "failed": 0},
            "flags": [True, False, None],
        }
    )


# --- non-leaking error messages --------------------------------------------------------


def test_forbidden_audit_data_error_never_echoes_the_value() -> None:
    with pytest.raises(ForbiddenAuditDataError) as excinfo:
        guard_payload({"password": SECRET_VALUE})
    message = str(excinfo.value)
    assert SECRET_VALUE not in message
    assert "password" in message


def test_forbidden_audit_data_error_never_echoes_email_value() -> None:
    email = "victim@example.com"
    with pytest.raises(ForbiddenAuditDataError) as excinfo:
        guard_payload({"note": email})
    assert email not in str(excinfo.value)


def test_forbidden_audit_data_error_never_echoes_stack_trace_body() -> None:
    body = "Traceback (most recent call last):\n  raise ValueError('leaked-secret-token-xyz')"
    with pytest.raises(ForbiddenAuditDataError) as excinfo:
        guard_payload({"detail": body})
    assert "leaked-secret-token-xyz" not in str(excinfo.value)


def test_forbidden_audit_data_error_exposes_key_path_and_reason_attrs() -> None:
    with pytest.raises(ForbiddenAuditDataError) as excinfo:
        guard_payload({"token": SECRET_VALUE})
    assert excinfo.value.key_path == "token"
    assert "credential" in excinfo.value.reason


# --- actor minimization ------------------------------------------------------------


def test_guard_actor_fields_returns_actor_id() -> None:
    assert guard_actor_fields({"actor_id": "user-123"}) == "user-123"


def test_guard_actor_fields_rejects_extra_field() -> None:
    with pytest.raises(ForbiddenAuditDataError) as excinfo:
        guard_actor_fields({"actor_id": "user-123", "email": "user@example.com"})
    assert excinfo.value.key_path == "email"


def test_guard_actor_fields_rejects_missing_actor_id() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_actor_fields({})


def test_guard_actor_fields_rejects_empty_actor_id() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_actor_fields({"actor_id": ""})


def test_guard_actor_fields_does_not_leak_extra_field_value() -> None:
    with pytest.raises(ForbiddenAuditDataError) as excinfo:
        guard_actor_fields({"actor_id": "user-123", "full_name": "Jane Doe"})
    assert "Jane Doe" not in str(excinfo.value)

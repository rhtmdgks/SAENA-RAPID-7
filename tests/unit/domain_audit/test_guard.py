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


# --- tokenizer acronym-boundary cases (critic SHOULD-FIX 3) ---------------------------


@pytest.mark.parametrize("key", ["authToken", "APIKey", "AuthToken", "apiKey"])
def test_guard_payload_rejects_credential_keys_camel_case_acronym_forms(key: str) -> None:
    # authToken -> ["auth", "token"] (token matches); APIKey -> ["apikey"]
    # (the whole acronym+word run merges into one token because the camel
    # boundary regex only splits at lowercase/digit -> UPPERCASE, so a
    # leading ALL-CAPS run stays fused — "apikey" still matches the
    # `apikey` pattern directly). Both forms are caught.
    with pytest.raises(ForbiddenAuditDataError):
        guard_payload({key: SECRET_VALUE})


def test_guard_payload_does_not_catch_acronym_immediately_followed_by_word() -> None:
    """Documents a real tokenizer gap (critic SHOULD-FIX 3) — see guard.py.

    "APIToken" tokenizes to a single fused token ["apitoken"] because the
    leading ALL-CAPS acronym run ("API") merges with the following word
    ("Token") with no lowercase/digit->UPPERCASE boundary between them, and
    "apitoken" does not match any pattern in _CREDENTIAL_KEY_PATTERNS
    (neither the single token "token" nor the two-token "api_key"). This is
    a documented, accepted residual gap for camelCase acronym+word keys with
    no separator — this codebase's actual payload field names are
    snake_case (see the AuditEvent contract), so it is not fixed with
    acronym-splitting heuristics here. Pinned as a gap, not asserted safe.
    """
    guard_payload({"APIToken": SECRET_VALUE})


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


# --- accepted limitation: value-side credential-shaped text is not caught -------------


def test_guard_payload_does_not_catch_secret_shaped_value_text() -> None:
    """Pins a documented, accepted gap — see guard.py module docstring.

    guard_payload inspects KEY names and specific VALUE PATTERNS (stack
    traces, exception frames, email shapes); it is not a general secret
    scanner. A credential-shaped string under an innocuous key currently
    passes. This test documents the CURRENT (accepted) behavior rather than
    asserting it is "safe" — if this test starts failing because the guard
    grew broader value scanning, that is an improvement and this test should
    be updated/removed, not treated as a regression.
    """
    # Deliberately does not raise — this is the pinned gap, not a bug fix.
    guard_payload({"note": "password=hunter2"})
    guard_payload({"details": "Authorization: Bearer abc123.def456.ghi789"})


# --- bytes values fail closed (critic SHOULD-FIX 1) -----------------------------------


def test_guard_payload_rejects_bytes_value() -> None:
    with pytest.raises(ForbiddenAuditDataError) as excinfo:
        guard_payload({"data": b"binary content"})
    assert excinfo.value.key_path == "data"


def test_guard_payload_rejects_bytearray_value() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_payload({"data": bytearray(b"binary content")})


def test_guard_payload_rejects_nested_bytes_value() -> None:
    with pytest.raises(ForbiddenAuditDataError) as excinfo:
        guard_payload({"items": [{"blob": b"\x00\x01\x02"}]})
    assert excinfo.value.key_path == "items[0].blob"


def test_guard_payload_rejects_bytes_at_root() -> None:
    with pytest.raises(ForbiddenAuditDataError):
        guard_payload(b"raw bytes payload")


def test_guard_payload_bytes_error_does_not_leak_content() -> None:
    secret_bytes = b"s3cr3t-binary-content-should-not-appear-in-error"
    with pytest.raises(ForbiddenAuditDataError) as excinfo:
        guard_payload({"data": secret_bytes})
    message = str(excinfo.value)
    assert "s3cr3t-binary-content-should-not-appear-in-error" not in message


def test_guard_payload_rejects_bytes_that_would_otherwise_hide_stack_trace() -> None:
    # Regression for the bug this fix closes: bytes is a Sequence[int], so
    # without an explicit bytes check this content would previously be
    # walked as a sequence of ints and NEVER string-checked for stack-trace
    # markers — silently bypassing the guard entirely. Now it must be
    # rejected outright (fail closed) instead.
    hidden_traceback = b"Traceback (most recent call last):\n  ..."
    with pytest.raises(ForbiddenAuditDataError):
        guard_payload({"detail": hidden_traceback})


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

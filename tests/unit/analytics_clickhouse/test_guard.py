"""Unit tests for `saena_analytics_clickhouse.guard` (w4-06 mission
deliverable 3: "REJECT raw/secret content, fail-closed, redacted error")."""

from __future__ import annotations

import pytest
from saena_analytics_clickhouse.errors import RawContentRejectedError
from saena_analytics_clickhouse.guard import guard_row_fields


def test_clean_fields_pass() -> None:
    guard_row_fields({"tenant_id": "acme-co", "query_text": "best crm"})  # does not raise


@pytest.mark.parametrize(
    "field_name",
    [
        "raw_response",
        "raw_html_body",
        "screenshot_b64",
        "response_body",
        "secret_token",
        "api_key",
        "PASSWORD",  # case-insensitive
    ],
)
def test_forbidden_field_name_rejected(field_name: str) -> None:
    with pytest.raises(RawContentRejectedError) as exc_info:
        guard_row_fields({field_name: "anything"})
    assert exc_info.value.context["reason"] == "forbidden_field_name"


def test_oversize_value_rejected() -> None:
    with pytest.raises(RawContentRejectedError) as exc_info:
        guard_row_fields({"metadata": "x" * 5000})
    assert exc_info.value.context["reason"] == "oversize_blob"


@pytest.mark.parametrize(
    "value",
    [
        "sk-" + "a" * 25,
        "AKIA" + "A" * 16,
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMe",
        "-----BEGIN RSA PRIVATE KEY-----",
        "ghp_" + "a" * 36,
    ],
)
def test_secret_shaped_value_rejected(value: str) -> None:
    with pytest.raises(RawContentRejectedError) as exc_info:
        guard_row_fields({"innocuous_field": value})
    assert exc_info.value.context["reason"] == "secret_shaped_value"


def test_rejected_error_never_leaks_value_in_message_or_context() -> None:
    secret_value = "sk-" + "b" * 30
    with pytest.raises(RawContentRejectedError) as exc_info:
        guard_row_fields({"innocuous_field": secret_value})
    rendered = str(exc_info.value.to_dict())
    assert secret_value not in rendered


def test_rejected_error_never_leaks_oversize_value() -> None:
    big_value = "y" * 5000
    with pytest.raises(RawContentRejectedError) as exc_info:
        guard_row_fields({"metadata": big_value})
    rendered = str(exc_info.value.to_dict())
    assert big_value not in rendered


def test_non_string_values_are_never_scanned_for_length_or_secret_shape() -> None:
    guard_row_fields({"contribution_score": 0.5, "count": 12345})  # does not raise

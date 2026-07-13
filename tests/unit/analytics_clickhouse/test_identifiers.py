"""Unit tests for `saena_analytics_clickhouse.identifiers` (w4-06)."""

from __future__ import annotations

import datetime as dt

import pytest
from saena_analytics_clickhouse.errors import RowValidationError
from saena_analytics_clickhouse.identifiers import (
    validate_nonempty_str,
    validate_tenant_id,
    validate_utc_datetime,
)


def test_valid_tenant_id_accepted() -> None:
    validate_tenant_id("acme-co")  # does not raise


def test_empty_tenant_id_rejected() -> None:
    with pytest.raises(RowValidationError):
        validate_tenant_id("")


def test_tenant_id_over_32_chars_rejected() -> None:
    with pytest.raises(RowValidationError):
        validate_tenant_id("a" * 33)


@pytest.mark.parametrize("value", ["ACME-CO", "acme_co", "-acme", "acme-", "acme co"])
def test_non_dns_safe_tenant_id_rejected(value: str) -> None:
    with pytest.raises(RowValidationError):
        validate_tenant_id(value)


def test_nonempty_str_rejects_empty() -> None:
    with pytest.raises(RowValidationError):
        validate_nonempty_str("", field_name="x")


def test_nonempty_str_rejects_over_max_length() -> None:
    with pytest.raises(RowValidationError):
        validate_nonempty_str("abc", field_name="x", max_length=2)


def test_utc_datetime_rejects_naive() -> None:
    with pytest.raises(RowValidationError):
        validate_utc_datetime(dt.datetime(2026, 7, 1), field_name="occurred_at")  # noqa: DTZ001


def test_utc_datetime_rejects_non_utc_offset() -> None:
    tz = dt.timezone(dt.timedelta(hours=9))
    with pytest.raises(RowValidationError):
        validate_utc_datetime(dt.datetime(2026, 7, 1, tzinfo=tz), field_name="occurred_at")


def test_utc_datetime_rejects_non_datetime() -> None:
    with pytest.raises(RowValidationError):
        validate_utc_datetime("2026-07-01", field_name="occurred_at")


def test_utc_datetime_accepts_aware_utc() -> None:
    validate_utc_datetime(dt.datetime(2026, 7, 1, tzinfo=dt.UTC), field_name="occurred_at")

"""Shared identifier type + field-validation helpers for row models.

This package is standalone (imports no other `saena_*` package — see
`pyproject.toml`'s Integrator note), so `TenantId` is redefined locally
rather than importing `saena_domain.identity.TenantId`. The DNS-safe slug
pattern below matches `docs/architecture/tenancy-model.md`'s CONFIRMED
format ("tenant_id 형식 = 불변 DNS-safe slug ≤32자", ADR-0014) exactly, so a
`tenant_id` this package accepts is guaranteed compatible with every other
store's own `tenant_id` values.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import NewType

from saena_analytics_clickhouse.errors import RowValidationError

TenantId = NewType("TenantId", str)

# DNS-safe slug, <=32 chars (tenancy-model.md, ADR-0014).
_TENANT_ID_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")


def validate_tenant_id(tenant_id: str, *, field_name: str = "tenant_id") -> None:
    """Raise `RowValidationError` if `tenant_id` is not a non-empty,
    <=32-char, DNS-safe slug (ADR-0014)."""
    if not tenant_id:
        raise RowValidationError(
            f"{field_name} must be a non-empty string", context={"field": field_name}
        )
    if len(tenant_id) > 32:
        raise RowValidationError(
            f"{field_name} exceeds 32 chars (ADR-0014 DNS-safe slug limit)",
            context={"field": field_name, "length": len(tenant_id)},
        )
    if not _TENANT_ID_PATTERN.match(tenant_id):
        raise RowValidationError(
            f"{field_name} {tenant_id!r} is not a DNS-safe slug (ADR-0014)",
            context={"field": field_name},
        )


def validate_nonempty_str(value: str, *, field_name: str, max_length: int | None = None) -> None:
    if not value:
        raise RowValidationError(
            f"{field_name} must be a non-empty string", context={"field": field_name}
        )
    if max_length is not None and len(value) > max_length:
        raise RowValidationError(
            f"{field_name} exceeds {max_length} chars",
            context={"field": field_name, "length": len(value), "max_length": max_length},
        )


def validate_utc_datetime(value: object, *, field_name: str) -> None:
    """Raise `RowValidationError` unless `value` is a timezone-AWARE
    `datetime` in UTC (offset exactly `timedelta(0)`).

    A naive `datetime` (no `tzinfo`) or a non-UTC-offset aware `datetime` is
    rejected outright — ClickHouse's `DateTime64(3, 'UTC')` columns
    (`schema.py`) assume every stored instant is already unambiguous UTC;
    silently assuming a naive value's timezone would be a correctness bug
    for out-of-order/replay tolerance and partition-boundary math
    (`toYYYYMM(occurred_at)`, ADR-0007 rev.2 "시간 파티션"). This is one of
    the mission's named negative tests ("malformed timestamp rejected").
    """
    if not isinstance(value, datetime):
        raise RowValidationError(
            f"{field_name} must be a datetime.datetime instance, got {type(value).__name__}",
            context={"field": field_name},
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise RowValidationError(
            f"{field_name} must be timezone-aware (UTC) — naive datetime rejected",
            context={"field": field_name},
        )
    if value.utcoffset() != timedelta(0):
        raise RowValidationError(
            f"{field_name} must be UTC (offset {value.utcoffset()} is not +00:00)",
            context={"field": field_name},
        )


def utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "TenantId",
    "utc_now",
    "validate_nonempty_str",
    "validate_tenant_id",
    "validate_utc_datetime",
]

"""Fail-closed guard against raw/secret content landing in an analytics row.

Mission requirement (w4-06): "Row models: only metadata/hash/ref columns —
NO raw response/screenshot/source. A helper that REJECTS (fail-closed) any
row carrying an obviously-raw field (oversize blob / secret-shaped) with a
redacted error." Spec basis: `docs/architecture/data-ownership.md`
Constraints ("No PII/secrets in event payloads — object refs + access
policy"), ADR-0007 rev.2 (ClickHouse = analytics store, never a blob store).

This is a HEURISTIC, defense-in-depth guard, not a content-scanning oracle —
it cannot prove a string is safe, only refuse the SHAPES that are obviously
unsafe: field names that name raw content, oversize string values (a
metadata/hash/ref column has no legitimate reason to be large), and values
that match a well-known secret-shaped pattern (API keys, AWS access key IDs,
JWTs, PEM private key headers). Every row model in `rows.py` calls
`guard_row_fields` from its own `__post_init__`, so construction itself is
the enforcement point — a row that fails this guard is never able to reach
`query.py`'s INSERT builder or any `ClickHouseExecutor` in the first place.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from saena_analytics_clickhouse.errors import RawContentRejectedError

# A metadata/hash/ref column (opaque object-storage ref, content hash,
# locale code, ...) has no legitimate reason to exceed this length. Chosen
# well above the longest legitimate field this package defines today
# (r4-04: `ObservationRow` no longer carries any raw query text at all —
# see `rows.py`/`query_privacy.py`; `query_ref`/`query_digest` are both
# short opaque ref/hash strings, `_OPAQUE_REF_MAX_LENGTH`=512 in `rows.py`)
# while still catching a raw HTML page / screenshot data-URI / full model
# response smuggled into a "metadata" field.
_MAX_FIELD_VALUE_LENGTH = 4096

# Field NAME markers that name raw content outright — checked
# case-insensitively as a substring match against the field name, never the
# value, so this catches `raw_response`, `raw_html_body`, `screenshot_b64`,
# `response_body`, `secret_token`, etc. regardless of exact naming.
_FORBIDDEN_FIELD_NAME_MARKERS = (
    "raw_response",
    "raw_content",
    "raw_html",
    "raw_body",
    "raw_screenshot",
    "screenshot",
    "response_body",
    "response_text",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "private_key",
)

# VALUE-shaped secret patterns — checked against string values regardless of
# field name (a caller could name the field innocuously and still smuggle a
# credential through). Each pattern is a well-known, low-false-positive
# secret shape; this is deliberately NOT a general entropy scanner (Ponytail:
# no speculative ML/entropy heuristics for a W4 adapter package).
_SECRET_SHAPED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style secret key
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),  # PEM private key
    re.compile(r"ghp_[A-Za-z0-9]{36}"),  # GitHub personal access token
)


def guard_row_fields(fields: Mapping[str, Any]) -> None:
    """Raise `RawContentRejectedError` if any `(name, value)` pair in
    `fields` looks like raw/secret content.

    Checks, in order (first match wins — the error is raised on the FIRST
    offending field found, never a batch report, so no offending value is
    ever accumulated into an error payload):

    1. Field NAME contains a forbidden marker (`_FORBIDDEN_FIELD_NAME_MARKERS`).
    2. String VALUE exceeds `_MAX_FIELD_VALUE_LENGTH` (oversize-blob heuristic).
    3. String VALUE matches a known secret shape (`_SECRET_SHAPED_PATTERNS`).

    The raised error's message and `context` NEVER include the offending
    value itself — only the field name and the reason category — so a
    caller logging this exception cannot accidentally leak the very secret
    it caught.
    """
    for name, value in fields.items():
        lowered_name = name.lower()
        if any(marker in lowered_name for marker in _FORBIDDEN_FIELD_NAME_MARKERS):
            raise RawContentRejectedError(
                f"field {name!r} has a forbidden raw-content-shaped name — value redacted",
                context={"field": name, "reason": "forbidden_field_name"},
            )
        if not isinstance(value, str):
            continue
        if len(value) > _MAX_FIELD_VALUE_LENGTH:
            raise RawContentRejectedError(
                f"field {name!r} exceeds {_MAX_FIELD_VALUE_LENGTH} chars "
                "(oversize-blob heuristic) — value redacted",
                context={
                    "field": name,
                    "reason": "oversize_blob",
                    "length": len(value),
                    "max_length": _MAX_FIELD_VALUE_LENGTH,
                },
            )
        for pattern in _SECRET_SHAPED_PATTERNS:
            if pattern.search(value):
                raise RawContentRejectedError(
                    f"field {name!r} matches a known secret-shaped pattern — value redacted",
                    context={"field": name, "reason": "secret_shaped_value"},
                )


__all__ = ["guard_row_fields"]

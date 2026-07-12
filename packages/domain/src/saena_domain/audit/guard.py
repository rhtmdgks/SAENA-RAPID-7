"""Forbidden-data guards for audit payloads (contract-catalog.md + ADR-0015).

`AuditEvent` retention is "contractual, immutable role; payload PII/secret
금지" (contract-catalog.md P0 row 12) and ADR-0015 fixes the audit error
footprint to `error_code` + `trace_id` only — "상세 진단 정보(스택 트레이스,
요청 원문)는 audit 계약 밖" (ADR-0015 :64). The audit-event JSON Schema
`$comment` on `payload` reiterates that PII/secret exclusion is a *runtime*
gate, not schema-enforceable content inspection — this module is that
runtime gate.

Rule of thumb enforced throughout: `ForbiddenAuditDataError` names the
offending key PATH only, never the offending VALUE — the whole point of the
guard is that the value may itself be a secret, so echoing it back in an
exception message (which may reach logs, tracebacks, or CI output) would
defeat the guard.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# --- credential-ish key detection -------------------------------------------------

# Matched case-insensitively against each mapping key. Deliberately substring
# style (not exact-match) so variants like `db_password`, `apiKey`,
# `x-api-key`, `Authorization`, `bearer_token` are all caught — the
# instruction lists these as representative, not exhaustive, so this errs
# toward over-blocking rather than under-blocking (audit ledger is
# immutable; a false positive is a rejected write, a false negative is a
# permanent leak).
_CREDENTIAL_KEY_PATTERNS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "private_key",
    "credential",
    "bearer",
)

# --- PII key detection -------------------------------------------------------------

# `actor_id` is the one identity field the AuditEvent contract explicitly
# allows (contract-catalog.md "ledger에는 actor_id만, 신원 매핑 분리 보관") —
# it must NOT be caught by this list even though it contains "id".
_PII_KEY_PATTERNS: tuple[str, ...] = (
    "email",
    "full_name",
    "phone",
)

# --- source-content key detection ---------------------------------------------------

# contract-catalog.md: PatchArtifact/SourceSnapshot carry customer source at
# "customer-proprietary 최고" sensitivity; the audit ledger stores hashes
# only, never the source content itself.
_SOURCE_CONTENT_KEY_PATTERNS: tuple[str, ...] = (
    "diff",
    "patch",
    "file_content",
)

# `patch_unit_id`-style keys are legitimate identifier references (see the
# AuditEvent contract's own `action` examples, `patch.unit.completed.v1`,
# and PatchArtifact's `patch_unit_id` idempotency-key component,
# contract-catalog.md P0 row 10) — NOT source content — even though their
# leading token is `patch`. `_matches_source_content` below only treats the
# single-token patterns (`diff`, `patch`) as forbidden when they are the
# FINAL token of the key (the key names the content itself, e.g. `patch`,
# `raw_diff`) — a key that continues with further identifier tokens after
# `patch`/`diff` (e.g. `patch_unit_id`) is an identifier reference, not raw
# content. The multi-token pattern `file_content` has no such carve-out: it
# is always content-shaped regardless of what follows.

# --- stack-trace / raw-exception content detection ----------------------------------

_STACK_TRACE_MARKERS: tuple[str, ...] = ("Traceback (most recent call last)",)

# Matches common "raw exception dump" shapes, e.g. `File "x.py", line 12, in
# foo` (Python traceback frame lines) — used as an additional signal beyond
# the literal "Traceback (most recent call last)" header, since a truncated
# dump might omit the header but still carry frame lines.
_EXCEPTION_FRAME_RE = re.compile(r'File "[^"]+", line \d+, in ')

# --- email-pattern value detection --------------------------------------------------

_EMAIL_VALUE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# --- error-detail shape (ADR-0015 common/v1/error-detail) ---------------------------

#: The only keys permitted inside an object that represents error
#: information in an audit payload — mirrors `common/error-detail/v1`
#: (`error_code`, `retryable`, `summary`) plus `trace_id`, which ADR-0015's
#: `AuditEvent` 에러 기록 범위 clause names as the sibling field recorded
#: alongside `error_code` ("error_code + trace_id만 기록한다"). Any other key
#: under an `error`-labelled object is rejected as excess diagnostic detail.
ERROR_DETAIL_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"error_code", "retryable", "summary", "trace_id"}
)

_ERROR_OBJECT_KEY_MARKERS: tuple[str, ...] = ("error", "exception")


class ForbiddenAuditDataError(ValueError):
    """Raised when a payload contains data the audit ledger must never store.

    The exception message names the offending key PATH (e.g.
    `"payload.user.password"`) and the violated category — it deliberately
    never includes the offending VALUE, because the value may itself be the
    secret/PII being rejected.
    """

    def __init__(self, key_path: str, reason: str) -> None:
        self.key_path = key_path
        self.reason = reason
        super().__init__(f"forbidden audit data at '{key_path}': {reason}")


def _join_path(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else key


def _index_path(parent: str, index: int) -> str:
    return f"{parent}[{index}]"


# Splits a key into lowercase word tokens across snake_case, kebab-case,
# space-separated, and camelCase boundaries — e.g. "X-Api-Key" -> ["x", "api",
# "key"], "dbPasswordHash" -> ["db", "password", "hash"], "patch_unit_id" ->
# ["patch", "unit", "id"]. Tokenization (rather than raw substring matching)
# is what lets a multi-word field like `patch_unit_id` pass while a
# single-token field literally named `patch` (or a token sequence containing
# it, e.g. `unified_diff`) is still caught — a forbidden pattern must appear
# as a whole token (or contiguous token run, for multi-token patterns like
# `api_key`/`full_name`), not as a substring of an unrelated word.
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN_SPLIT_RE = re.compile(r"[_\-\s]+")


def _tokenize_key(name: str) -> list[str]:
    camel_split = _CAMEL_BOUNDARY_RE.sub("_", name)
    return [tok.lower() for tok in _TOKEN_SPLIT_RE.split(camel_split) if tok]


def _find_pattern_spans(tokens: list[str], patterns: Sequence[str]) -> list[tuple[int, int]]:
    """Return `(start, end)` token-index spans where a pattern matches contiguously."""
    spans: list[tuple[int, int]] = []
    for pattern in patterns:
        pattern_tokens = pattern.split("_")
        n = len(pattern_tokens)
        for i in range(len(tokens) - n + 1):
            if tokens[i : i + n] == pattern_tokens:
                spans.append((i, i + n))
    return spans


def _matches_any(name: str, patterns: Sequence[str]) -> bool:
    return bool(_find_pattern_spans(_tokenize_key(name), patterns))


def _matches_source_content(name: str) -> bool:
    """Like `_matches_any` for `_SOURCE_CONTENT_KEY_PATTERNS`, with a trailing-identifier carve-out.

    Multi-token patterns (`file_content`) are forbidden wherever they match.
    Single-token patterns (`diff`, `patch`) are forbidden only when the match
    is the FINAL token run in the key — see the module-level comment above
    `_SOURCE_CONTENT_KEY_PATTERNS` for why (`patch_unit_id` must pass; a bare
    `patch`/`raw_diff` field must not).
    """
    tokens = _tokenize_key(name)
    for start, end in _find_pattern_spans(tokens, _SOURCE_CONTENT_KEY_PATTERNS):
        pattern_is_multi_token = end - start > 1
        is_final_token_run = end == len(tokens)
        if pattern_is_multi_token or is_final_token_run:
            return True
    return False


def _guard_error_object(obj: Mapping[str, Any], path: str) -> None:
    """Enforce the error-detail shape on an object keyed like `error`/`exception`."""
    excess = set(obj.keys()) - ERROR_DETAIL_ALLOWED_KEYS
    if excess:
        offending_key = sorted(excess)[0]
        raise ForbiddenAuditDataError(
            _join_path(path, offending_key),
            "error information must conform to the error-detail shape "
            "(error_code/retryable/summary[/trace_id]) — no other fields "
            "(e.g. stack traces or raw request content) are permitted",
        )


def _guard_string_value(value: str, path: str) -> None:
    for marker in _STACK_TRACE_MARKERS:
        if marker in value:
            raise ForbiddenAuditDataError(path, "value contains stack-trace content")
    if _EXCEPTION_FRAME_RE.search(value):
        raise ForbiddenAuditDataError(path, "value contains raw exception-dump content")
    if _EMAIL_VALUE_RE.match(value.strip()):
        raise ForbiddenAuditDataError(path, "value looks like a PII email address")


def _guard_key(key: str, path: str) -> None:
    if _matches_any(key, _CREDENTIAL_KEY_PATTERNS):
        raise ForbiddenAuditDataError(path, "key name indicates credential/secret data")
    if _matches_any(key, _PII_KEY_PATTERNS):
        raise ForbiddenAuditDataError(path, "key name indicates PII beyond actor_id")
    if _matches_source_content(key):
        raise ForbiddenAuditDataError(
            path, "key name indicates customer source content — ledger stores hashes only"
        )


def guard_payload(payload: Any, *, _path: str = "") -> None:
    """Recursively reject forbidden data anywhere in an audit payload.

    Walks mappings and sequences (excluding `str`/`bytes`, which are treated
    as scalar leaves) and, at every level, rejects:

    - credential-ish keys (password, passwd, secret, token, api_key, apikey,
      authorization, private_key, credential, bearer, and case-insensitive
      substring variants of each).
    - stack-trace content ("Traceback (most recent call last)" or raw
      Python exception-frame dumps) appearing as a string VALUE anywhere.
    - source-content style keys (diff/patch/file_content) — the ledger
      stores hashes of customer source, never the content itself.
    - PII beyond `actor_id`: keys named email/full_name/phone, or any string
      value that matches an email address pattern.
    - objects keyed like `error`/`exception` that carry fields beyond the
      error-detail shape (`error_code`, `retryable`, `summary`, `trace_id`).

    Raises `ForbiddenAuditDataError` naming the offending key PATH only —
    never the offending value. Does nothing (returns `None`) if `payload`
    contains no forbidden data.
    """
    if isinstance(payload, Mapping):
        error_like_keys = {k for k in payload if _matches_any(str(k), _ERROR_OBJECT_KEY_MARKERS)}
        for key, value in payload.items():
            key_str = str(key)
            child_path = _join_path(_path, key_str)
            _guard_key(key_str, child_path)
            if key in error_like_keys and isinstance(value, Mapping):
                _guard_error_object(value, child_path)
            guard_payload(value, _path=child_path)
        return
    if isinstance(payload, str):
        _guard_string_value(payload, _path)
        return
    if isinstance(payload, Sequence):
        for index, item in enumerate(payload):
            guard_payload(item, _path=_index_path(_path, index))
        return
    # Scalars other than str (int, float, bool, None) carry no forbidden
    # shape to inspect.


def guard_error_detail(error_detail: Mapping[str, Any], *, _path: str = "error") -> None:
    """Validate a standalone error-detail object against ADR-0015's shape.

    Equivalent to the object-shape check `guard_payload` applies to nested
    `error`/`exception`-keyed objects, exposed directly for callers building
    an audit entry's top-level `error_code` (ADR-0015 "AuditEvent 에러 기록
    범위: error_code + trace_id만 기록한다") from a richer error-detail value
    before truncating it to the permitted footprint.
    """
    _guard_error_object(error_detail, _path)
    guard_payload(dict(error_detail), _path=_path)


#: Fields an `AuditEvent` entry's `actor_id`-equivalent slot may legitimately
#: carry — anything else on an "actor" object is rejected as identity data
#: beyond the contract's PII-minimization allowance.
_ACTOR_ALLOWED_KEYS = frozenset({"actor_id"})


def guard_actor_fields(actor: Mapping[str, Any]) -> str:
    """Strip/reject actor fields down to the single `actor_id` the ledger may store.

    contract-catalog.md ActorContext row: "부인방지 장기 ↔ PII 최소화: ledger
    에는 actor_id만, 신원 매핑 분리 보관" — audit entries carry `actor_id`
    only, never a name/email/session or other identity attribute. Returns
    the `actor_id` string. Raises `ForbiddenAuditDataError` if `actor`
    carries any key other than `actor_id`, or if `actor_id` is missing.
    """
    excess = set(actor.keys()) - _ACTOR_ALLOWED_KEYS
    if excess:
        raise ForbiddenAuditDataError(
            sorted(excess)[0],
            "actor data must be minimized to actor_id only "
            "(contract-catalog.md ActorContext PII-minimization rule)",
        )
    if "actor_id" not in actor:
        raise ForbiddenAuditDataError("actor_id", "actor_id is required for actor minimization")
    actor_id = actor["actor_id"]
    if not isinstance(actor_id, str) or not actor_id:
        raise ForbiddenAuditDataError("actor_id", "actor_id must be a non-empty string")
    return actor_id

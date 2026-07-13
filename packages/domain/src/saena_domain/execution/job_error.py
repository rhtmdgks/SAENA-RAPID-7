"""`JobError` — canonical structured error representation for execution-domain
outcomes (ADR-0015 canonical error model).

`to_error_detail_payload()`'s output matches
`packages/contracts/json-schema/common/error-detail/v1/error-detail.schema.json`
EXACTLY (`error_code`, `retryable`, `summary`; that schema is `closed`,
`additionalProperties: false`, exactly those 3 fields required) — the
`redacted_detail` field below is domain-internal only and is NEVER included
in that payload's output. ADR-0015 "`AuditEvent` 에러 기록 범위": the audit
ledger records only `error_code` + `trace_id`; detailed diagnostics belong in
a separate access-restricted diagnostic store, explicitly out of ADR-0015's
scope (and this module's).

`JobError` NEVER carries a stack trace or a raw content/source blob
(ADR-0015 Constraints: "`detail`/`summary` 필드에 customer source, secret,
PII 원문 포함 금지"; `contract-catalog.md` `AuditEvent` PII/secret ban,
carried over to this value object even though it is not itself an
`AuditEvent`). `summary` and every `redacted_detail` value are guarded
against stack-trace-shaped and oversized content at construction time — see
`_reject_unsafe_text`. This is a best-effort heuristic gate (a determined
caller can still construct a `redacted_detail` value this heuristic does not
catch), not a proof of safety — but it converts the common accidental case
(`summary=str(exc)`, `redacted_detail={"trace": traceback.format_exc()}`)
into a hard construction-time rejection rather than a silent leak.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from saena_domain.execution.errors import JobErrorValidationError

# Same shape as common/error-detail/v1's error_code pattern
# (`^saena\.[a-z_]+\.[a-z_]+$`) — duplicated here rather than imported since
# there is no Python constant exported by that JSON Schema file to reuse
# (mirrors identity.tenant.TENANT_ID_PATTERN's "byte-for-byte in sync,
# duplicated not imported" precedent for the same reason: the contract has
# no importable Python artifact of its own outside the generated pydantic
# model, and pulling in a full model here for a pattern check would be
# disproportionate).
_ERROR_CODE_PATTERN = re.compile(r"^saena\.[a-z_]+\.[a-z_]+$")

# ADR-0015 "에러 taxonomy — 9 카테고리"
# (docs/decisions/ADR-0015-canonical-error-model.md). `JobError.error_code`'s
# category segment MUST be one of these — execution-domain errors ride the
# SAME taxonomy the sync API and event/audit paths use, not a bespoke
# vocabulary (contrast `saena_domain.identity.errors`, which predates this
# closed-list interpretation and uses `"identity"` as its own ad hoc
# category — `JobError` is a new call site introduced by this patch unit, so
# it holds the ADR-0015 9-category line from the start rather than adding a
# 10th ad hoc category to the taxonomy).
KNOWN_ERROR_CATEGORIES: frozenset[str] = frozenset(
    {
        "validation",
        "auth",
        "policy_denied",
        "conflict",
        "not_found",
        "rate_limited",
        "upstream_engine",
        "unavailable",
        "internal",
    }
)

# error-detail.schema.json #/properties/summary: maxLength 500.
_SUMMARY_MAX_LENGTH = 500
# No contract bound exists for redacted_detail (it is domain-internal, never
# serialized to the wire shape) — this module imposes its own conservative
# bound so a caller cannot use it as a back door to smuggle an
# effectively-unbounded blob past the wire-shape's own 500-char summary cap.
_DETAIL_VALUE_MAX_LENGTH = 500
_DETAIL_MAX_ENTRIES = 16

# Heuristic stack-trace/source-blob markers this module refuses to accept in
# summary/redacted_detail. Not exhaustive — a sufficiently disguised blob can
# still slip past a substring heuristic — but this catches the common,
# accidental case of passing `str(exc)` or `traceback.format_exc()` straight
# through instead of pre-redacting it, turning "never carries" into an
# enforced runtime gate rather than documentation-only guidance.
_STACK_TRACE_MARKERS: tuple[str, ...] = (
    "Traceback (most recent call last)",
    '\n  File "',
)


def _reject_unsafe_text(*, field_name: str, value: str, max_length: int) -> None:
    if len(value) > max_length:
        raise JobErrorValidationError(
            f"{field_name} exceeds {max_length} chars ({len(value)}) — JobError "
            "never carries large blobs (ADR-0015 stack-trace/raw-content ban)",
            context={"field": field_name, "length": len(value), "max_length": max_length},
        )
    for marker in _STACK_TRACE_MARKERS:
        if marker in value:
            raise JobErrorValidationError(
                f"{field_name} looks like a stack trace (contains {marker!r}) — "
                "JobError NEVER carries stack traces (ADR-0015 Constraints)",
                context={"field": field_name},
            )


@dataclass(frozen=True, slots=True)
class JobError:
    """Structured, redacted execution-domain error value.

    `redacted_detail` is a small, closed-shape mapping of ALREADY-REDACTED
    string key/value pairs the caller has prepared (e.g.
    `{"gate_id": "lint"}`) — this module validates it is small and
    non-stack-trace-shaped, it does NOT perform redaction itself (redaction
    of arbitrary upstream content is out of this pure-domain package's
    scope; callers must pass already-safe values).
    """

    error_code: str
    summary: str
    retryable: bool
    redacted_detail: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _ERROR_CODE_PATTERN.fullmatch(self.error_code):
            raise JobErrorValidationError(
                f"error_code {self.error_code!r} does not match "
                f"{_ERROR_CODE_PATTERN.pattern!r} (common/error-detail/v1 shape)",
                context={"error_code": self.error_code},
            )
        category = self.error_code.split(".")[1]
        if category not in KNOWN_ERROR_CATEGORIES:
            raise JobErrorValidationError(
                f"error_code category {category!r} is not one of the ADR-0015 "
                f"9 categories {sorted(KNOWN_ERROR_CATEGORIES)!r}",
                context={"error_code": self.error_code, "category": category},
            )
        if not self.summary:
            raise JobErrorValidationError(
                "summary must be a non-empty string", context={"field": "summary"}
            )
        _reject_unsafe_text(
            field_name="summary", value=self.summary, max_length=_SUMMARY_MAX_LENGTH
        )
        if len(self.redacted_detail) > _DETAIL_MAX_ENTRIES:
            raise JobErrorValidationError(
                f"redacted_detail carries {len(self.redacted_detail)} entries, "
                f"more than the {_DETAIL_MAX_ENTRIES} this module allows",
                context={"entry_count": len(self.redacted_detail)},
            )
        for key, value in self.redacted_detail.items():
            _reject_unsafe_text(
                field_name=f"redacted_detail[{key!r}]",
                value=value,
                max_length=_DETAIL_VALUE_MAX_LENGTH,
            )

    def to_error_detail_payload(self) -> dict[str, Any]:
        """Wire shape matching `common/error-detail/v1` EXACTLY.

        `redacted_detail` is deliberately excluded — that schema is closed
        (`additionalProperties: false`, exactly 3 fields) and ADR-0015's
        audit scope is `error_code` + `trace_id` only, never free-form
        detail.
        """
        return {
            "error_code": self.error_code,
            "retryable": self.retryable,
            "summary": self.summary,
        }


__all__ = ["KNOWN_ERROR_CATEGORIES", "JobError"]

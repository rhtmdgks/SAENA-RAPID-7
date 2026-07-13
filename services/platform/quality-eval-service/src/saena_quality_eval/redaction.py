"""Redaction helpers — the ONLY place in this package that is allowed to
look at a raw secret snippet or a raw stack-trace-shaped string before it is
turned into a `saena_domain.execution.JobError` (which itself independently
rejects stack-trace-shaped `summary`/`redacted_detail` text at construction
time, `saena_domain.execution.job_error._reject_unsafe_text` — this module's
job is to redact secrets, which that layer does NOT attempt, and to fail
CLOSED (never accidentally forward a raw value) rather than rely solely on
that downstream guard.

mission item 10 ("REDACTION: failure reasons never leak stack traces or
source blobs; VerificationResult carries redacted detail only"): every
`gates.py` gate that could otherwise be tempted to embed raw upstream text
(secret-scanner matches, lint tool stdout, a build log) in a `JobError`
routes through this module first.
"""

from __future__ import annotations

_SECRET_MASK = "[REDACTED]"

#: Same heuristic markers `saena_domain.execution.job_error` rejects — kept
#: here too (byte-for-byte, same rationale as that module's own duplicated-
#: not-imported precedent) so this module can PROACTIVELY strip/replace a
#: stack-trace-shaped substring before ever handing text to `JobError`,
#: rather than relying on that downstream constructor to raise.
_STACK_TRACE_MARKERS: tuple[str, ...] = (
    "Traceback (most recent call last)",
    '\n  File "',
)


def redact_secret_snippet(rule_id: str, file_path: str, line: int) -> str:
    """Build a redacted-safe description of a secret-scanner finding.

    Deliberately takes NO raw matched-text argument at all — the caller
    (`gates.secret_scan`) must not even be able to pass the raw snippet in
    by mistake; only the rule id / location (never customer source content)
    are safe to surface in a `JobError.redacted_detail`/`summary`.
    """
    return f"{rule_id} finding at {file_path}:{line} ({_SECRET_MASK})"


def contains_stack_trace_marker(text: str) -> bool:
    """True iff `text` looks like a Python stack trace (same heuristic
    `saena_domain.execution.job_error` uses to reject unsafe text)."""
    return any(marker in text for marker in _STACK_TRACE_MARKERS)


def redact_stack_trace(text: str) -> str:
    """Replace `text` with a fixed-detail placeholder if it looks like a
    stack trace; otherwise return it unchanged.

    Used ahead of any `JobError(summary=..., redacted_detail=...)`
    construction that derives its text from a tool's raw output (e.g. a
    build/lint/typecheck log line) — this converts "an upstream tool
    happened to emit `str(exc)`/`traceback.format_exc()`" into a safe fixed
    string instead of letting it propagate into a `VerificationResult`.
    """
    if contains_stack_trace_marker(text):
        return "[REDACTED: stack-trace-shaped content omitted]"
    return text


def truncate(text: str, *, max_length: int = 200) -> str:
    """Bound `text` to `max_length` chars (never mid-multibyte — this module
    only ever handles `str`, not raw bytes), appending a truncation marker
    when it was cut. Applied to any tool-derived free text before it reaches
    a `JobError` field, on top of (not instead of) `redact_stack_trace`."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "...[truncated]"


__all__ = [
    "contains_stack_trace_marker",
    "redact_secret_snippet",
    "redact_stack_trace",
    "truncate",
]

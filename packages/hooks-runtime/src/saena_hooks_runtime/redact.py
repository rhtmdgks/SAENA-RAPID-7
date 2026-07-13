"""Redaction helpers — detail/audit text must never carry secret values or
raw source file contents (task instructions: "Redaction: reason/detail
never contain secret values or source file contents").

Two complementary strategies, both applied every time a hook builds a
detail string that might reference something sensitive:

1. `redact_known` — literal substring replacement for values the caller
   KNOWS are sensitive (e.g. `SecretFinding.raw_value` from a secret-scan
   adapter). This is the primary guarantee: it does not depend on a regex
   guessing right, it removes exactly the value the caller says is a
   secret, wherever it appears in the text.
2. `redact_patterns` — best-effort pattern-based masking for
   commonly-shaped credentials (AWS keys, GitHub tokens, OpenAI-style
   tokens, PEM key blocks, bearer/authorization headers, generic
   `key=value`/`key: value` assignments whose key name looks secret-ish)
   that might appear in text the caller did NOT already identify as a
   known secret (e.g. inside a raw command string being denied). Defense
   in depth, not the primary guarantee — `redact_known` is.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_MASK = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens (ghp_/gho_/ghu_/ghs_/ghr_)
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style secret keys
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----.*?-----END[ A-Z]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{10,}"),
    re.compile(r"(?i)\b(authorization|api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*\S+"),
)


def redact_patterns(text: str) -> str:
    """Best-effort pattern-based masking. Never raises; unmatched text is
    returned unchanged."""
    out = text
    for pattern in _PATTERNS:
        out = pattern.sub(_MASK, out)
    return out


def redact_known(text: str, secrets: Iterable[str]) -> str:
    """Replace every literal occurrence of each value in `secrets` with
    `[REDACTED]`, then apply `redact_patterns` as a second pass.

    Longer secrets are replaced first so a short secret that happens to be
    a substring of a longer one does not leave a partial mask behind.
    """
    out = text
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        out = out.replace(secret, _MASK)
    return redact_patterns(out)


__all__ = ["redact_known", "redact_patterns"]

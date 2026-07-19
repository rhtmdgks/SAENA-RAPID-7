"""Secret-shape refusal guard (local copy — deliberate duplication).

This is the 4th deliberate copy of `_SECRET_SHAPED_PATTERNS` in this repo
(siblings: `saena_strategy_skill_bank.intake`, `saena_domain.measurement.
evidence`, `saena_hooks_runtime.redact`). Repo convention: security guards are
NEVER imported across package boundaries — each enforcement point owns its own
copy so no refactor elsewhere can silently weaken this one. Includes the
hyphen-infix `sk-live-…` shape (c5-06 audit).

The guard REFUSES to write any contract/report/evidence value that looks
secret-shaped. On refusal the offending *field path* is reported — never the
value itself.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from saena_pilot.errors import SecretShapedValueError

_SECRET_SHAPED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"gh[opsu]_[A-Za-z0-9]{36}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"\b[sr]k_(live|test)_[A-Za-z0-9]{10,}"),
    re.compile(
        r"\b[sr]k-(live|test)-[A-Za-z0-9]{10,}"
    ),  # hyphen-infix variant (sk-live-…, c5-06 audit)
    # Modern default-issuance formats (VULN-2, w6-13). The `sk-[A-Za-z0-9]{20,}`
    # run above breaks on the `-proj-`/`-svcacct-` hyphen, so these need their
    # own anchors:
    re.compile(r"sk-(proj|svcacct|admin)-[A-Za-z0-9_-]{20,}"),  # OpenAI project/service keys
    re.compile(r"github_pat_[A-Za-z0-9_]{22,}"),  # GitHub fine-grained PAT
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),  # GitLab PAT
)


def is_secret_shaped(value: str) -> bool:
    """True iff `value` matches any known secret shape."""
    return any(pattern.search(value) for pattern in _SECRET_SHAPED_PATTERNS)


def guard_value(value: Any, *, path: str) -> None:
    """Refuse a single scalar if it is secret-shaped. Non-strings pass."""
    if isinstance(value, str) and is_secret_shaped(value):
        raise SecretShapedValueError(
            f"refusing to record secret-shaped value at {path!r} "
            "(value withheld from this message and from all pilot artifacts)",
            context={"path": path},
        )


def guard_tree(obj: Any, *, path: str = "$") -> None:
    """Recursively refuse any secret-shaped string in a JSON-ish tree.

    Applied before every contract write, report write, and evidence append.
    Keys are guarded too — a secret pasted as a mapping key must not leak.
    """
    if isinstance(obj, str):
        guard_value(obj, path=path)
        return
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if isinstance(key, str):
                guard_value(key, path=f"{path}.{key}")
            guard_tree(value, path=f"{path}.{key}")
        return
    if isinstance(obj, Sequence) and not isinstance(obj, (bytes, bytearray)):
        for index, item in enumerate(obj):
            guard_tree(item, path=f"{path}[{index}]")

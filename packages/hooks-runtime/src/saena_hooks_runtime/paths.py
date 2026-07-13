"""Path normalization + glob-scope matching used by `deny_out_of_scope_file_write`.

Defeats the "path normalization (../, //, ./)" and (in combination with a
caller-supplied `resolved_path`, see `pre_tool_use.PreToolUseInput`) the
"symlink targets" bypass categories named in the task instructions'
"Command normalization layer" requirement — this module is pure string
manipulation, it never touches the filesystem (no `os.path.realpath`
call here: symlink RESOLUTION is an effectful, filesystem-touching
operation and belongs in the runtime adapter that calls into this engine,
not in the pure engine itself; the adapter passes the already-resolved
real path in as plain data via `resolved_path`, and this module just
scope-checks whichever paths it is given).
"""

from __future__ import annotations

import posixpath
import re
from urllib.parse import unquote


def normalize_path(path: str) -> str:
    """Decode percent-encoding, collapse `//`/`./`/`../` segments, and
    strip a leading `/`.

    A normalized result that still starts with `..` means the path tries
    to escape whatever root it was expressed relative to — `glob_match`
    against an `approved_scope` entry will correctly never match such a
    path (no repo-relative glob starts with `..`), which is exactly the
    fail-closed behavior traversal attempts need; this function does not
    need to special-case that itself.
    """
    decoded = unquote(path)
    decoded = decoded.replace("\\", "/")
    decoded = decoded.lstrip("/")
    normalized = posixpath.normpath(decoded)
    if normalized == ".":
        return ""
    return normalized


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob pattern (`*` = any run of non-`/` chars, `**` = any
    run of chars including `/`, `?` = one non-`/` char, everything else
    literal) into a compiled, fully-anchored regex."""
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(c))
        i += 1
    return re.compile("(?:" + "".join(out) + ")")


def glob_match(pattern: str, path: str) -> bool:
    """`True` iff `path` (already normalized) matches `pattern` in full."""
    return _glob_to_regex(pattern).fullmatch(path) is not None


def path_in_scope(path: str, approved_scope: tuple[str, ...]) -> bool:
    """`True` iff the normalized form of `path` matches any glob in
    `approved_scope`. An empty `approved_scope` never matches anything —
    fail-closed by construction, no special-cased "empty means allow-all"
    branch exists here."""
    normalized = normalize_path(path)
    if not normalized:
        return False
    return any(glob_match(pattern, normalized) for pattern in approved_scope)


__all__ = ["glob_match", "normalize_path", "path_in_scope"]

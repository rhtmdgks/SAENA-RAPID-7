"""File/glob scope, protected-path, and filesystem-boundary guards.

Three independent guards, all fail-closed, applied to every write a patch
unit attempts (`runner.py` calls all three, in the order below, before any
byte reaches `WorktreeHandle.write_file`):

1. `guard_protected_path` — a fixed, structural denylist (CLAUDE.md
   "Protected paths") that no `approved_scope` can ever override. Checked
   FIRST and unconditionally: even a contract that (erroneously or
   maliciously) named a protected path in its own `approved_scope`/`files`
   cannot make this guard pass.
2. `guard_scope` — the contract's OWN scope: a write target must be BOTH
   declared in the executing patch unit's `files` list AND matched by at
   least one `approved_scope` glob. Two contract-carried lists, not one —
   `files` is a per-unit closed manifest, `approved_scope` is the
   plan-level glob budget; a target absent from either is out of scope.
3. `resolve_within_worktree` — the filesystem-boundary guard: resolves the
   candidate path against the worktree root and rejects anything that
   escapes it, whether via `..`-traversal, an absolute path, or a symlink
   whose target resolves outside the root.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from saena_agent_runner.errors import (
    OutOfScopeWriteError,
    PathTraversalError,
    ProtectedPathWriteError,
)

# CLAUDE.md "Protected paths" section, mirrored verbatim for this package's
# own write boundary (agent-runner is the ONLY Wave 3 job kind with Git
# write capability at all, ADR-0004 — so it is the one place these paths
# must be structurally unwritable, not just documentation). Checked as a
# path-PREFIX match against the write target's POSIX-normalized relative
# path, never a substring match (so e.g. `docs/specifically-not-specs/x`
# is not falsely caught by a naive substring check against `docs/specs`).
PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    ".cursor/rules/",
    "docs/specs/",
    "packages/contracts/",
    "packages/schemas/",
    "events/",
    "workflows/",
    "deploy/",
    ".claude/settings",
    ".git/",
    ".github/",
)


def _normalize_relative(relative_path: str) -> str:
    """Normalize `relative_path` to a POSIX-style, `.`-free relative path.

    Rejects (raises `PathTraversalError`) any input that is empty, absolute
    (leading `/`), or contains a literal `..` path segment — this check runs
    BEFORE any filesystem call, so it is the first line of defense against
    traversal even for a worktree adapter whose root does not exist yet.
    """
    if not relative_path:
        raise PathTraversalError("empty relative_path is not a valid write target", context={})
    candidate = PurePosixPath(relative_path)
    if candidate.is_absolute():
        raise PathTraversalError(
            f"relative_path {relative_path!r} is absolute — not permitted",
            context={"relative_path": relative_path},
        )
    if any(part == ".." for part in candidate.parts):
        raise PathTraversalError(
            f"relative_path {relative_path!r} contains a '..' traversal segment",
            context={"relative_path": relative_path},
        )
    return candidate.as_posix()


def guard_protected_path(relative_path: str) -> None:
    """Raise `ProtectedPathWriteError` iff `relative_path` falls under a
    structurally protected prefix (CLAUDE.md), regardless of scope."""
    normalized = _normalize_relative(relative_path)
    for prefix in PROTECTED_PATH_PREFIXES:
        if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
            raise ProtectedPathWriteError(
                f"{relative_path!r} falls under the protected path prefix {prefix!r} "
                "(CLAUDE.md Protected paths) — denied regardless of approved_scope",
                context={"relative_path": relative_path, "protected_prefix": prefix},
            )


def is_in_approved_scope(relative_path: str, approved_scope: Sequence[str]) -> bool:
    """`True` iff `relative_path` matches at least one `approved_scope` glob."""
    normalized = _normalize_relative(relative_path)
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in approved_scope)


def guard_scope(
    relative_path: str,
    *,
    patch_unit_files: Sequence[str],
    approved_scope: Sequence[str],
) -> None:
    """Raise `OutOfScopeWriteError` unless `relative_path` is BOTH declared
    in `patch_unit_files` AND matched by an `approved_scope` glob."""
    normalized = _normalize_relative(relative_path)
    if normalized not in {_normalize_relative(f) for f in patch_unit_files}:
        raise OutOfScopeWriteError(
            f"{relative_path!r} is not declared in this patch unit's own "
            "files list — refusing write",
            context={"relative_path": relative_path},
        )
    if not is_in_approved_scope(normalized, approved_scope):
        raise OutOfScopeWriteError(
            f"{relative_path!r} is not matched by any approved_scope glob",
            context={"relative_path": relative_path, "approved_scope": list(approved_scope)},
        )


def resolve_within_worktree(root: Path, relative_path: str) -> Path:
    """Resolve `relative_path` against `root`, rejecting any escape.

    `root` MUST already exist (a worktree handle's own root directory).
    Follows symlinks via `Path.resolve()` and then verifies the FINAL
    resolved path is still a descendant of the resolved root — this is
    what catches a symlink whose target points outside the worktree (the
    pre-resolve `..`-segment check in `_normalize_relative` alone would not
    catch that, since a symlink can point outside without the REQUESTED
    relative path itself containing `..`).

    Raises `PathTraversalError` on any escape.
    """
    normalized = _normalize_relative(relative_path)
    resolved_root = root.resolve(strict=True)
    candidate = root / normalized
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:  # pragma: no cover - defensive; resolve(strict=False) rarely raises
        raise PathTraversalError(
            f"failed to resolve {relative_path!r} against the worktree root",
            context={"relative_path": relative_path},
        ) from exc
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PathTraversalError(
            f"{relative_path!r} resolves outside the worktree root (symlink escape or traversal)",
            context={"relative_path": relative_path},
        ) from exc
    return resolved


__all__ = [
    "PROTECTED_PATH_PREFIXES",
    "guard_protected_path",
    "guard_scope",
    "is_in_approved_scope",
    "resolve_within_worktree",
]

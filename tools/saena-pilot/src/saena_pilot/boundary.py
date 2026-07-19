"""Customer-repository boundary validation — fail-closed.

Order of operations is load-bearing:

1. The RAW argument must be absolute (rejected before any resolution — a
   relative path is a usage error, not something to be repaired).
2. `os.path.realpath` resolves symlinks and normalizes every `..` segment
   BEFORE all subsequent checks, so traversal tricks and symlink escapes are
   evaluated against the real location.
3. Containment against the RAPID-7 root is checked before git-shape checks:
   a path inside RAPID-7 is a boundary violation regardless of what it is.
4. The path must be a git repository ROOT (`git -C <path> rev-parse
   --show-toplevel` == itself), with at least one commit (HEAD needed for
   evidence binding).
5. Working-tree state (dirty / detached HEAD / nested repos) becomes
   per-mode-classified findings: write modes BLOCK, read modes WARN.

No check ever chdirs into the customer repository (`git -C` only) and no
subprocess uses a shell. Spaces and non-ASCII path segments are supported
throughout because argv is always a list.
"""

from __future__ import annotations

import os
from pathlib import Path

from saena_pilot._git import (
    git_head_sha,
    git_toplevel,
    is_detached_head,
    is_dirty,
)
from saena_pilot.errors import BoundaryViolationError, ValidationFailedError
from saena_pilot.models import BoundaryReport, Finding, Mode, Severity


def _is_within(inner: Path, outer: Path) -> bool:
    try:
        inner.relative_to(outer)
    except ValueError:
        return False
    return True


def _find_nested_repos(root: Path) -> list[str]:
    """Repo-relative paths of every `.git` (dir or gitfile) BELOW the root.

    The root's own `.git` is expected and skipped; each nested repo found is
    recorded and its subtree pruned (its internals are not walked)."""
    nested: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        if here == root:
            if ".git" in dirnames:
                dirnames.remove(".git")
            continue
        if ".git" in dirnames or ".git" in filenames:
            nested.append(str(here.relative_to(root)))
            dirnames.clear()  # do not descend into the nested repo
            continue
    return sorted(nested)


def validate_customer_repo(customer_repo: str, *, rapid7_root: Path, mode: Mode) -> BoundaryReport:
    """Validate the customer repo path for `mode`, fail-closed.

    Raises `ValidationFailedError` for shape failures, `BoundaryViolationError`
    for containment failures, and returns a `BoundaryReport` whose findings
    are already BLOCK/WARN-classified for `mode`. Callers must still honor
    `report.blocked`.
    """
    if not os.path.isabs(customer_repo):
        raise ValidationFailedError(
            f"--customer-repo must be an absolute path, got {customer_repo!r}",
            context={"customer_repo": customer_repo},
        )

    resolved = Path(os.path.realpath(customer_repo))
    rapid7_real = Path(os.path.realpath(rapid7_root))

    if not resolved.exists():
        raise ValidationFailedError(
            f"customer repo does not exist: {customer_repo!r} (resolved: {resolved})",
            context={"customer_repo": customer_repo, "resolved": str(resolved)},
        )
    if not resolved.is_dir():
        raise ValidationFailedError(
            f"customer repo is not a directory: {resolved}",
            context={"resolved": str(resolved)},
        )

    if resolved == rapid7_real:
        raise BoundaryViolationError(
            "customer repo resolves to the RAPID-7 repository itself "
            f"({resolved}) — the pilot never operates on its own repo",
            context={"resolved": str(resolved), "rapid7_root": str(rapid7_real)},
        )
    if _is_within(resolved, rapid7_real):
        raise BoundaryViolationError(
            f"customer repo {resolved} is nested inside the RAPID-7 repository "
            f"{rapid7_real} — refusing",
            context={"resolved": str(resolved), "rapid7_root": str(rapid7_real)},
        )
    if _is_within(rapid7_real, resolved):
        raise BoundaryViolationError(
            f"the RAPID-7 repository {rapid7_real} is nested inside the customer "
            f"repo {resolved} — refusing",
            context={"resolved": str(resolved), "rapid7_root": str(rapid7_real)},
        )

    toplevel = git_toplevel(resolved)
    if toplevel is None:
        raise ValidationFailedError(
            f"customer repo is not a git repository: {resolved}",
            context={"resolved": str(resolved)},
        )
    toplevel_real = Path(os.path.realpath(toplevel))
    if toplevel_real != resolved:
        raise ValidationFailedError(
            f"customer repo must be the git repository ROOT: {resolved} is inside "
            f"the repository rooted at {toplevel_real}",
            context={"resolved": str(resolved), "toplevel": str(toplevel_real)},
        )

    head_sha = git_head_sha(resolved)
    if head_sha is None:
        raise ValidationFailedError(
            f"customer repo has no resolvable HEAD commit: {resolved} — evidence "
            "binding requires a commit",
            context={"resolved": str(resolved)},
        )

    state_severity = Severity.BLOCK if mode.writes_customer else Severity.WARN
    findings: list[Finding] = []
    if is_dirty(resolved):
        findings.append(
            Finding(
                code="dirty_tree",
                severity=state_severity,
                detail="customer working tree has uncommitted changes",
                context={"resolved": str(resolved)},
            )
        )
    if is_detached_head(resolved):
        findings.append(
            Finding(
                code="detached_head",
                severity=state_severity,
                detail="customer repository HEAD is detached",
                context={"resolved": str(resolved)},
            )
        )
    nested = _find_nested_repos(resolved)
    if nested:
        findings.append(
            Finding(
                code="nested_repos",
                severity=state_severity,
                detail=f"nested git repositories found below the customer root: {nested}",
                context={"nested": nested},
            )
        )

    return BoundaryReport(
        customer_root=resolved,
        head_sha=head_sha,
        findings=tuple(findings),
    )

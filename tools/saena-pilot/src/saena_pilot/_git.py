"""Git subprocess helpers.

Every git call in this package goes through `run_git`: list-argv subprocess
(`shell=True` is banned package-wide), `git -C <path>` addressing so the
pilot NEVER chdirs into the customer repository, text mode, no exceptions on
nonzero exit (callers interpret returncode).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — list argv, never shell
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def git_toplevel(path: Path) -> Path | None:
    """The repository toplevel containing `path`, or None if not in a repo."""
    result = run_git(path, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        return None
    top = result.stdout.strip()
    return Path(top) if top else None


def git_head_sha(repo: Path) -> str | None:
    result = run_git(repo, "rev-parse", "HEAD")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def is_dirty(repo: Path) -> bool:
    """True iff the working tree has any staged/unstaged/untracked change."""
    result = run_git(repo, "status", "--porcelain")
    return bool(result.stdout.strip())


def is_detached_head(repo: Path) -> bool:
    result = run_git(repo, "symbolic-ref", "-q", "HEAD")
    return result.returncode != 0


def branch_exists(repo: Path, branch: str) -> bool:
    result = run_git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    return result.returncode == 0

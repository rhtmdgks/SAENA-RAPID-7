"""Customer-side write isolation via a dedicated git worktree.

`implement` is the ONLY mode with customer-side write capability, and it
writes exclusively inside a dedicated worktree:

    <customer-parent>/<customer-basename>.saena-worktrees/<run-id>
    branch saena-pilot/<run-id>

created via `git -C <customer> worktree add …` (list argv, never a shell,
never chdir into the customer repo). An existing directory or branch is a
distinct collision error — the pilot NEVER forces over either.

Defense in depth: `create_customer_worktree` asserts the mode capability flag
(`Mode.writes_customer`) itself, so even a buggy caller in a read-only mode
cannot create the worktree. Read modes have no code path into this function.
"""

from __future__ import annotations

from pathlib import Path

from saena_pilot._git import branch_exists, run_git
from saena_pilot.errors import BoundaryViolationError, WorktreeCollisionError
from saena_pilot.models import Mode


def worktree_container(customer_root: Path) -> Path:
    return customer_root.parent / f"{customer_root.name}.saena-worktrees"


def worktree_path(customer_root: Path, run_id: str) -> Path:
    return worktree_container(customer_root) / run_id


def branch_name(run_id: str) -> str:
    return f"saena-pilot/{run_id}"


def create_customer_worktree(customer_root: Path, run_id: str, *, mode: Mode) -> Path:
    """Create the dedicated worktree for this run, or raise.

    Raises `BoundaryViolationError` if called for any mode without customer
    write capability, `WorktreeCollisionError` for an existing directory or
    branch (never resolved with `--force`)."""
    if not mode.writes_customer:
        raise BoundaryViolationError(
            f"mode {mode.value!r} carries no customer write capability — refusing "
            "to create a customer worktree",
            context={"mode": mode.value},
        )

    target = worktree_path(customer_root, run_id)
    branch = branch_name(run_id)

    if target.exists():
        raise WorktreeCollisionError(
            f"worktree directory already exists: {target} — refusing to reuse or "
            "force; inspect/remove it manually",
            context={"worktree": str(target)},
        )
    if branch_exists(customer_root, branch):
        raise WorktreeCollisionError(
            f"branch {branch!r} already exists in {customer_root} — refusing to "
            "reuse or force; a previous run may own it",
            context={"branch": branch, "customer_root": str(customer_root)},
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    result = run_git(customer_root, "worktree", "add", str(target), "-b", branch)
    if result.returncode != 0:
        raise WorktreeCollisionError(
            f"git worktree add failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}",
            context={"worktree": str(target), "branch": branch},
        )
    return target

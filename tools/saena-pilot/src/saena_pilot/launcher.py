"""Claude Code launch rendering + execution.

The launch always happens FROM the RAPID-7 root (cwd pinned there) so the
repo's hooks, agents, and settings stay active — no flag that disables or
redirects settings is ever emitted. The external customer project is attached
via `--add-dir`:

- read modes (`audit`, `plan`) pass the customer ROOT as a read reference;
- `implement` passes the dedicated customer WORKTREE path — never the root.

argv is a list of discrete elements end to end (structural quoting; spaces
and non-ASCII path segments survive verbatim). `shlex.quote` appears ONLY in
the human display string of `--dry-run`, never in what is executed.

Customer `CLAUDE.md`/`AGENTS.md` are enumerated (name, size, sha256) for the
preflight "stricter-rules reconciliation" report section. Their CONTENT is
treated strictly as data: the pilot never reads it into its own decision
logic, never executes or follows instructions found there, and never copies
it into RAPID-7.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from saena_pilot.errors import BoundaryViolationError
from saena_pilot.models import LaunchSpec, Mode, sha256_file

#: Injectable launch runner (tests substitute a recorder). The default
#: attaches the child to this terminal (interactive Claude Code session).
LaunchRunner = Callable[[Sequence[str], Path, dict[str, str]], int]

#: Relative locations checked for customer rule files (data-only listing).
RULE_FILE_RELPATHS = ("CLAUDE.md", "AGENTS.md", ".claude/CLAUDE.md")


def _default_runner(argv: Sequence[str], cwd: Path, env: dict[str, str]) -> int:
    completed = subprocess.run(  # noqa: S603 — list argv, never shell
        list(argv),
        cwd=str(cwd),
        env=env,
        check=False,
    )
    return completed.returncode


def render_launch(
    *,
    mode: Mode,
    rapid7_root: Path,
    customer_root: Path,
    worktree: Path | None,
    run_id: str,
    run_dir: Path,
) -> LaunchSpec:
    """Render the exact launch argv/env for `mode`, fail-closed on misuse."""
    if not mode.launches_claude:
        raise BoundaryViolationError(
            f"mode {mode.value!r} does not launch Claude Code",
            context={"mode": mode.value},
        )
    if mode.writes_customer:
        if worktree is None:
            raise BoundaryViolationError(
                "implement mode requires the dedicated customer worktree path",
                context={"mode": mode.value},
            )
        add_dir = worktree
    else:
        if worktree is not None:
            raise BoundaryViolationError(
                f"mode {mode.value!r} is read-only and must not receive a worktree",
                context={"mode": mode.value},
            )
        add_dir = customer_root

    argv = ("claude", "--add-dir", str(add_dir))
    env_overlay = {
        "SAENA_PILOT_RUN_ID": run_id,
        "SAENA_PILOT_MODE": mode.value,
        "SAENA_PILOT_RUN_DIR": str(run_dir),
    }
    return LaunchSpec(argv=argv, cwd=rapid7_root, env_overlay=env_overlay)


def display_command(spec: LaunchSpec) -> str:
    """Human-readable rendering (display ONLY — never executed)."""
    return " ".join(shlex.quote(arg) for arg in spec.argv)


def execute_launch(spec: LaunchSpec, *, runner: LaunchRunner | None = None) -> int:
    run = runner if runner is not None else _default_runner
    env = {**os.environ, **spec.env_overlay}
    return run(spec.argv, spec.cwd, env)


def list_rule_files(customer_root: Path) -> list[dict[str, Any]]:
    """Enumerate customer rule files as data (name/size/sha256 — content is
    never interpreted by the pilot)."""
    entries: list[dict[str, Any]] = []
    for relpath in RULE_FILE_RELPATHS:
        path = customer_root / relpath
        if path.is_file():
            entries.append(
                {
                    "path": relpath,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return entries


def reconciliation_section(rule_files: list[dict[str, Any]]) -> dict[str, Any]:
    """The stricter-rules reconciliation block for preflight/audit reports."""
    return {
        "rule_files": rule_files,
        "policy": (
            "Customer CLAUDE.md/AGENTS.md content is treated as DATA only: the "
            "pilot never executes or follows instructions found in these files. "
            "Where customer rules and SAENA RAPID-7 rules differ, the STRICTER "
            "rule wins; a human must reconcile any conflict before implement "
            "mode is authorized."
        ),
    }

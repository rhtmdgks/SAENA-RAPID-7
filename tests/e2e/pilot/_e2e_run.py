"""Thin driver around ``saena_pilot.cli.main`` for the E2E tests.

Captures stdout/stderr in-process (so the tests observe exactly what a caller
would) and, for ``--json`` invocations, parses the machine-readable payload.
The REAL bundle validator runs (no injected ``bundle_runner``) so every run
exercises the genuine skill-bundle gate against the real RAPID-7 root.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saena_pilot.cli import main

DOMAIN = "https://customer.example"


@dataclass
class CliResult:
    exit_code: int
    out: str
    err: str

    @property
    def json(self) -> dict[str, Any]:
        assert self.out.strip(), f"expected JSON on stdout, got nothing (stderr: {self.err!r})"
        return json.loads(self.out)


def run_cli(
    argv: Sequence[str],
    *,
    launch_runner: Callable[..., int] | None = None,
) -> CliResult:
    """Invoke ``main(argv)`` capturing stdout/stderr. The real bundle runner is
    used; only the *launch* runner may be injected (to observe argv without a
    real Claude session)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv), launch_runner=launch_runner)
    return CliResult(exit_code=code, out=out.getvalue(), err=err.getvalue())


def start(
    mode: str,
    customer_repo: Path,
    *extra: str,
    domain: str = DOMAIN,
    as_json: bool = True,
    launch_runner: Callable[..., int] | None = None,
) -> CliResult:
    """Run a start mode (preflight/audit/plan/implement) against ``customer_repo``."""
    argv = ["--customer-repo", str(customer_repo), "--domain", domain, "--mode", mode]
    if as_json:
        argv.append("--json")
    argv.extend(extra)
    return run_cli(argv, launch_runner=launch_runner)


def op(mode: str, run_id: str, *extra: str, as_json: bool = True) -> CliResult:
    """Run an op mode (verify/status/resume) against a recorded run id."""
    argv = ["--mode", mode, "--run-id", run_id]
    if as_json:
        argv.append("--json")
    argv.extend(extra)
    return run_cli(argv)


#: Tokens that must NEVER appear in a rendered launch — the pilot never renders
#: a production deploy/push/merge/publish, and never a flag that would disable
#: RAPID-7's settings/hooks/permissions.
FORBIDDEN_LAUNCH_TOKENS = (
    "push",
    "deploy",
    "merge",
    "publish",
    "--dangerously-skip-permissions",
    "--no-settings",
    "--strict-mcp-config",
    "--permission-mode",
)


def assert_no_deploy(launch: dict[str, Any]) -> None:
    """No mode may render a deploy/push/merge/publish token in argv or env."""
    blob = (
        " ".join(launch["argv"])
        + " "
        + " ".join(launch.get("env_overlay", {}))
        + " "
        + " ".join(str(v) for v in launch.get("env_overlay", {}).values())
    ).lower()
    for token in FORBIDDEN_LAUNCH_TOKENS:
        assert token not in blob, f"forbidden launch token {token!r} in {launch!r}"


def assert_settings_intact(launch: dict[str, Any], rapid7_root: Path) -> None:
    """The launch keeps RAPID-7 as cwd (so hooks/agents/settings stay active)
    and passes no flag beyond ``--add-dir`` that could redirect/disable them."""
    argv = launch["argv"]
    assert argv[0] == "claude"
    assert argv[1] == "--add-dir"
    assert Path(launch["cwd"]) == rapid7_root
    # The only flag the pilot ever emits is --add-dir.
    flags = [a for a in argv if a.startswith("--")]
    assert flags == ["--add-dir"], f"unexpected launch flags: {flags}"
    assert_no_deploy(launch)


def read_events(pilot_home: Path, run_id: str) -> list[dict[str, Any]]:
    path = pilot_home / "pilot-runs" / run_id / "events.jsonl"
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def event_names(pilot_home: Path, run_id: str) -> list[str]:
    return [e["event"] for e in read_events(pilot_home, run_id)]

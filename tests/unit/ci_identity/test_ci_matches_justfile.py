"""Local <-> CI identity check (w2-22, ADR-0018 lockstep).

Parses `.github/workflows/ci.yml` and `justfile` and asserts the CI pipeline
mirrors the two-lane split (w2-20): a deterministic unit lane that excludes
`tests/integration/**` (`-m "not integration"`, identical to justfile's
`test` recipe) and a separate `integration` job that runs the real
Temporal/testcontainers lane (`just test-integration`, `-m integration`).

This makes drift between the CI pipeline and the justfile recipes a FAILING
TEST rather than a silent divergence — the whole point of ADR-0018's
"CI == `just verify`" lockstep guarantee. This test itself runs in the unit
lane it is asserting about (`tests/unit/**`, not `tests/integration/**`), so
it is exercised on every PR.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_JUSTFILE = _REPO_ROOT / "justfile"

# Matches a pytest invocation's `-m "..."` marker-selector expression, e.g.
# `-m "not integration"` or `-m integration`.
_MARKER_SELECTOR_RE = re.compile(r"-m\s+(\"[^\"]+\"|'[^']+'|\S+)")


def _load_ci_workflow() -> dict[str, Any]:
    return yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))


def _extract_marker_selector(command: str) -> str | None:
    """Return the normalized `-m` marker expression from a shell command, if any."""
    match = _MARKER_SELECTOR_RE.search(command)
    if match is None:
        return None
    return match.group(1).strip("\"'")


def _justfile_recipe_body(recipe_name: str) -> str:
    """Return the raw indented-line body of a `justfile` recipe by name.

    `justfile` recipes are `name:` (or `name arg:`) followed by indented
    lines until the next non-indented, non-comment, non-blank line.
    """
    lines = _JUSTFILE.read_text(encoding="utf-8").splitlines()
    header_re = re.compile(rf"^{re.escape(recipe_name)}(\s|:)")
    start = None
    for i, line in enumerate(lines):
        if header_re.match(line) and line.rstrip().endswith(":"):
            start = i + 1
            break
    assert start is not None, f"justfile: no recipe named {recipe_name!r} found"
    body_lines: list[str] = []
    for line in lines[start:]:
        if line.strip() == "":
            continue
        if not line.startswith((" ", "\t")):
            break
        body_lines.append(line)
    assert body_lines, f"justfile: recipe {recipe_name!r} has an empty body"
    return "\n".join(body_lines)


def _find_job(workflow: dict[str, Any], job_name: str) -> dict[str, Any]:
    jobs = workflow.get("jobs", {})
    assert job_name in jobs, f"ci.yml: no job named {job_name!r} found. Jobs: {sorted(jobs)}"
    return jobs[job_name]


def _job_run_commands(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in job.get("steps", []) if "run" in step]


def test_unit_job_selector_matches_justfile_test_recipe() -> None:
    """CI `unit` job's pytest selector must equal justfile `test` recipe's."""
    workflow = _load_ci_workflow()
    unit_job = _find_job(workflow, "unit")
    run_commands = _job_run_commands(unit_job)

    pytest_commands = [cmd for cmd in run_commands if "pytest" in cmd]
    assert pytest_commands, "ci.yml unit job: no pytest invocation found"
    ci_selector = _extract_marker_selector(pytest_commands[0])
    assert ci_selector is not None, (
        f"ci.yml unit job: pytest command has no -m marker selector (got: {pytest_commands[0]!r})"
    )

    justfile_test_body = _justfile_recipe_body("test")
    justfile_selector = _extract_marker_selector(justfile_test_body)
    assert justfile_selector is not None, (
        f"justfile `test` recipe has no -m marker selector (got: {justfile_test_body!r})"
    )

    assert ci_selector == justfile_selector == "not integration", (
        "CI unit-lane pytest selector must be byte-identical to justfile `test` "
        f"recipe's selector (ADR-0018 lockstep). CI={ci_selector!r} "
        f"justfile={justfile_selector!r}"
    )


def test_integration_job_exists_and_runs_test_integration_recipe() -> None:
    """CI must have a separate `integration` job that runs the integration lane."""
    workflow = _load_ci_workflow()
    integration_job = _find_job(workflow, "integration")
    run_commands = _job_run_commands(integration_job)

    justfile_selector = _extract_marker_selector(_justfile_recipe_body("test-integration"))
    assert justfile_selector == "integration", (
        f"justfile `test-integration` recipe must select `-m integration` "
        f"(got: {justfile_selector!r})"
    )

    runs_just_recipe = any("just test-integration" in cmd for cmd in run_commands)
    runs_identical_selector = any(
        _extract_marker_selector(cmd) == "integration" for cmd in run_commands
    )
    assert runs_just_recipe or runs_identical_selector, (
        "ci.yml `integration` job must run `just test-integration` (or an "
        "identical `-m integration` pytest selector) — ADR-0018 lockstep. "
        f"Commands found: {run_commands!r}"
    )


def test_integration_job_is_not_continue_on_error() -> None:
    """The integration job is a real gate — it must not silently soft-fail."""
    workflow = _load_ci_workflow()
    integration_job = _find_job(workflow, "integration")
    assert integration_job.get("continue-on-error") is not True, (
        "ci.yml `integration` job must not be continue-on-error: it is a "
        "real required gate, not an advisory job (w2-22 task spec)"
    )
    for step in integration_job.get("steps", []):
        assert step.get("continue-on-error") is not True, (
            f"ci.yml `integration` job step must not be continue-on-error: {step!r}"
        )

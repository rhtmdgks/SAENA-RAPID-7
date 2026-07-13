"""Self-verifying proof for the failure-mode required-lane HARD-FAILURE guard
(MUST-FIX B, conftest.py::pytest_sessionfinish).

When `SAENA_MEASUREMENT_FAILURE_REQUIRED=1` (set only by the
`just measurement-failure-modes` named gate + its CI job), the required
failure-mode lane must NEVER pass without actually running its real-Postgres
failure/replay/rollback/conflict rows. Any skipped required integration test —
or zero passed, or zero collected — is a HARD FAILURE (exit 6, non-zero,
non-5). Optional/local invocation (flag unset) keeps the honest Docker-absent
skip.

Proven by running pytest AS A SUBPROCESS (the guard aborts the whole session,
so it cannot be exercised in-process). This module is itself container-free —
it spawns subprocesses and asserts exit codes — so it must run on every host,
Docker-present or not; it excludes its own tests from every child selection to
avoid recursion.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Marked `integration` so the `just measurement-failure-modes -m integration`
# gate collects these guard-proof tests; the conftest EXEMPTS this module from
# the Docker-absent skip + the required-container accounting (it is container-
# free — only spawns subprocesses and asserts exit codes).
pytestmark = pytest.mark.integration

_THIS_DIR = Path(__file__).resolve().parent
_REQUIRED_ENV_VAR = "SAENA_MEASUREMENT_FAILURE_REQUIRED"
_HARD_FAIL_EXIT = 6
_TOLERATED_NO_TESTS_EXIT = 5
_NO_MATCH_K = "this_k_matches_no_failure_test_whatsoever_c5closure"
# Never re-select this guard file's own tests in a child run.
_NO_RECURSE = "not test_failure_required_guard"


def _run_child(*, required_flag: bool, docker_absent: bool, k_extra: str | None = None):
    env = dict(os.environ)
    if required_flag:
        env[_REQUIRED_ENV_VAR] = "1"
    else:
        env.pop(_REQUIRED_ENV_VAR, None)
    if docker_absent:
        env["DOCKER_HOST"] = "tcp://127.0.0.1:1"
    k_expr = _NO_RECURSE if k_extra is None else f"({k_extra}) and ({_NO_RECURSE})"
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            str(_THIS_DIR),
            "-m",
            "integration",
            "-k",
            k_expr,
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(_THIS_DIR),
        env=env,
    )


def test_required_docker_absent_hard_fails() -> None:
    result = _run_child(required_flag=True, docker_absent=True)
    combined = result.stdout + result.stderr
    assert result.returncode not in (0, _TOLERATED_NO_TESTS_EXIT), (
        "REQUIRED failure-mode lane with Docker absent must HARD FAIL (non-zero, "
        f"non-5) — never a green '0 passed, N skipped'; got {result.returncode}:\n{combined}"
    )
    assert result.returncode == _HARD_FAIL_EXIT, (
        f"expected the infra-absent hard-fail exit {_HARD_FAIL_EXIT}; "
        f"got {result.returncode}:\n{combined}"
    )
    assert "HARD FAILURE" in combined, f"expected the guard reason message:\n{combined}"


def test_required_zero_collected_hard_fails() -> None:
    result = _run_child(required_flag=True, docker_absent=False, k_extra=_NO_MATCH_K)
    combined = result.stdout + result.stderr
    assert result.returncode == _HARD_FAIL_EXIT, (
        "REQUIRED failure-mode lane collecting ZERO integration tests must hard-fail; "
        f"got {result.returncode}:\n{combined}"
    )
    assert "HARD FAILURE" in combined, f"expected the guard reason message:\n{combined}"


def test_optional_docker_absent_is_honest_skip() -> None:
    result = _run_child(required_flag=False, docker_absent=True)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        "OPTIONAL failure-mode lane (flag unset) with Docker absent must be an honest "
        f"skip, exit 0; got {result.returncode}:\n{combined}"
    )
    assert "HARD FAILURE" not in combined, (
        f"the required guard must NOT fire when the flag is unset:\n{combined}"
    )

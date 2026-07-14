"""Self-verifying proof for the failure-mode required-lane HARD-FAILURE guard
(MUST-FIX B, conftest.py::pytest_sessionfinish).

When `SAENA_MEASUREMENT_FAILURE_REQUIRED=1` (set only by the
`just measurement-failure-modes` named gate + its CI job), the required
failure-mode lane must NEVER pass without actually running its real-Postgres
failure/replay/rollback/conflict rows. Any skipped required integration test —
or zero passed, or zero collected — is a HARD FAILURE (exit 6, non-zero,
non-5). Optional/local invocation (flag unset) keeps the honest Docker-absent
skip.

Also proves the REQUIRED-SCENARIO COMPLETENESS guard (`_failure_completeness.
py`, wired into `conftest.py::pytest_sessionfinish`): the checks above only
ever see the SELECTED set (`session.items`) — a caller who narrows the run via
`-k` / `--deselect` / a single-node path / `PYTEST_ADDOPTS` can leave that
selected set fully passing while running only a FRACTION of the 31-scenario
required manifest, going green on a partial run. The completeness guard
compares the authoritative manifest (independent of what pytest happened to
select) against what actually executed-and-PASSED, so any such partial
selection is a HARD FAILURE too.

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
_REPO_ROOT = _THIS_DIR.parent.parent.parent
_REQUIRED_ENV_VAR = "SAENA_MEASUREMENT_FAILURE_REQUIRED"
_HARD_FAIL_EXIT = 6
_TOLERATED_NO_TESTS_EXIT = 5
_NO_MATCH_K = "this_k_matches_no_failure_test_whatsoever_c5closure"
# Never re-select this guard file's own tests in a child run.
_NO_RECURSE = "not test_failure_required_guard"

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
import _failure_completeness as _failure_complete  # noqa: E402


def _run_child(
    *,
    required_flag: bool,
    docker_absent: bool,
    k_extra: str | None = None,
    required_value: str = "1",
):
    env = dict(os.environ)
    if required_flag:
        env[_REQUIRED_ENV_VAR] = required_value
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


def test_required_arms_on_non_canonical_truthy_value() -> None:
    # Critic-F SHOULD-FIX: arming is fail-SAFE, not exact `== "1"`. A caller
    # who set the var to `true` (or `yes`, or `" 1 "` with whitespace) still
    # gets the REQUIRED lane — a typo must never silently downgrade it to the
    # optional/honest-skip lane. Docker absent + `true` => still exit 6.
    for value in ("true", "yes", " 1 "):
        result = _run_child(required_flag=True, docker_absent=True, required_value=value)
        combined = result.stdout + result.stderr
        assert result.returncode == _HARD_FAIL_EXIT, (
            f"{_REQUIRED_ENV_VAR}={value!r} must still ARM the required lane "
            f"(fail-safe), hard-failing exit {_HARD_FAIL_EXIT} when Docker absent; "
            f"got {result.returncode}:\n{combined}"
        )


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


# --------------------------------------------------------------------------- #
# REQUIRED-SCENARIO COMPLETENESS guard proofs (MUST-FIX B). Docker IS present
# for every case below (these are partial-SELECTION attacks, not infra-absent
# ones) — a caller narrowing the run via `-k` / `--deselect` / a single-node
# path / `PYTEST_ADDOPTS` must HARD FAIL (exit 6) even though every selected
# test actually passes, because the manifest's other required scenarios never
# ran. Reproduced (pre-fix) as: `-k <single test>` -> exit 0, 1 passed,
# 34 deselected — a green partial run.
# --------------------------------------------------------------------------- #

_SINGLE_TARGET_K = "test_fraud_did_scalar_is_zero_net_of_control_not_the_raw_movement"
_SINGLE_TARGET_NODE = (
    "tests/integration/measurement_failure/test_f9_fraud_repoint.py::"
    "test_fraud_did_scalar_is_zero_net_of_control_not_the_raw_movement"
)
_COVERAGE_MATRIX_META_NODE_K = "test_failure_mode_coverage_matrix"
# `--deselect` matches node ids the way pytest actually COLLECTED them for
# THIS invocation, which is rootdir-relative when invoked (as the real
# `just measurement-failure-modes` gate does) from the repo root against the
# directory path — so this target and the invocation below both use the
# repo-relative form/cwd, never `_THIS_DIR`-prefixed absolute paths (those
# silently match ZERO collected items and the `--deselect` becomes a no-op).
_DESELECT_TARGET = (
    "tests/integration/measurement_failure/test_failure_mode_coverage_matrix.py::"
    "test_real_postgres_matrix_rows_actually_ran_when_docker_is_available"
)


def test_required_single_k_selection_hard_fails_completeness() -> None:
    """`-k <one required test>` deselects the other 30 manifest scenarios —
    the SELECTED set fully passes (1 passed), but the completeness guard must
    reject the run as covering only a fraction of the required manifest."""
    result = _run_child(required_flag=True, docker_absent=False, k_extra=_SINGLE_TARGET_K)
    combined = result.stdout + result.stderr
    assert result.returncode not in (0, _TOLERATED_NO_TESTS_EXIT), (
        "a single `-k` selection under the required flag must HARD FAIL "
        f"(non-zero, non-5) — never a green partial run; got {result.returncode}:\n{combined}"
    )
    assert result.returncode == _HARD_FAIL_EXIT, (
        f"expected the completeness hard-fail exit {_HARD_FAIL_EXIT}; "
        f"got {result.returncode}:\n{combined}"
    )
    assert "required-scenario completeness" in combined, (
        f"expected the completeness guard's reason message:\n{combined}"
    )
    assert "did not execute-and-PASS" in combined, (
        f"expected the missing-scenario reason:\n{combined}"
    )


def test_required_deselect_one_node_hard_fails_completeness() -> None:
    """`--deselect` of exactly ONE required node (with everything else
    selected) must still hard-fail — one un-run manifest scenario is enough,
    matching the E2E lane's contract. Invoked from the repo root against a
    repo-relative directory path and deselect target — the SAME node-id shape
    the real `just measurement-failure-modes` gate uses (an absolute-path
    invocation against a relative deselect target, or vice versa, silently
    fails to match and the deselect becomes a no-op — reproduced while
    developing this test)."""
    env = dict(os.environ)
    env[_REQUIRED_ENV_VAR] = "1"
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/measurement_failure",
            "-m",
            "integration",
            "-k",
            _NO_RECURSE,
            "--deselect",
            _DESELECT_TARGET,
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == _HARD_FAIL_EXIT, (
        "deselecting a single required node under the required flag must HARD FAIL "
        f"(exit {_HARD_FAIL_EXIT}); got {result.returncode}:\n{combined}"
    )
    assert "required-scenario completeness" in combined, (
        f"expected the completeness guard's reason message:\n{combined}"
    )


def test_required_single_node_path_hard_fails_completeness() -> None:
    """Invoking pytest against a SINGLE node's file path (rather than the
    whole directory) is the most direct partial-selection shape — must still
    hard-fail even though pytest's own summary shows the one selected test
    PASSED. Invoked from the repo root with a repo-relative node id (same
    node-id shape as the deselect/collect-only proofs — see their
    docstrings)."""
    env = dict(os.environ)
    env[_REQUIRED_ENV_VAR] = "1"
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            _SINGLE_TARGET_NODE,
            "-m",
            "integration",
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == _HARD_FAIL_EXIT, (
        "a single-node-path invocation under the required flag must HARD FAIL "
        f"(exit {_HARD_FAIL_EXIT}); got {result.returncode}:\n{combined}"
    )
    assert "required-scenario completeness" in combined, (
        f"expected the completeness guard's reason message:\n{combined}"
    )


def test_required_coverage_matrix_meta_node_only_hard_fails_completeness() -> None:
    """Selecting ONLY the coverage-matrix meta-tests (a real, Docker-using
    subset that legitimately passes on its own) is still missing every OTHER
    required scenario — the guard must reject it exactly like any other
    partial selection, proving the completeness check is not fooled by a
    selection that happens to include some real integration coverage."""
    env = dict(os.environ)
    env[_REQUIRED_ENV_VAR] = "1"
    k_expr = f"({_COVERAGE_MATRIX_META_NODE_K}) and ({_NO_RECURSE})"
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/measurement_failure",
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
        cwd=str(_REPO_ROOT),
        env=env,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == _HARD_FAIL_EXIT, (
        "selecting only the coverage-matrix meta node set under the required flag "
        f"must HARD FAIL (exit {_HARD_FAIL_EXIT}); got {result.returncode}:\n{combined}"
    )
    assert "required-scenario completeness" in combined, (
        f"expected the completeness guard's reason message:\n{combined}"
    )


def test_required_pytest_addopts_selection_hard_fails_completeness() -> None:
    """`PYTEST_ADDOPTS=-k <single test>` is functionally identical to a `-k`
    CLI flag from pytest's perspective — must be caught the same way. Set
    directly in the child env (not merged via `_run_child`, which already
    uses `-k` for its own recursion guard) to prove the addopts-only path
    independently."""
    env = dict(os.environ)
    env[_REQUIRED_ENV_VAR] = "1"
    # `PYTEST_ADDOPTS` is parsed with `shlex.split` — an UNQUOTED multi-word
    # `-k` expression only consumes the single next token as its value, and
    # the remaining bareword tokens (`and`, `not`, ...) are then misread as
    # file/dir path arguments (`ERROR: file or directory not found: and`).
    # Quote the whole expression exactly like a shell caller must.
    env["PYTEST_ADDOPTS"] = f'-k "{_SINGLE_TARGET_K} and {_NO_RECURSE}"'
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/measurement_failure",
            "-m",
            "integration",
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == _HARD_FAIL_EXIT, (
        "PYTEST_ADDOPTS-driven partial selection under the required flag must HARD "
        f"FAIL (exit {_HARD_FAIL_EXIT}); got {result.returncode}:\n{combined}"
    )
    assert "required-scenario completeness" in combined, (
        f"expected the completeness guard's reason message:\n{combined}"
    )


# --------------------------------------------------------------------------- #
# DRIFT meta-test: the manifest's node-id set must equal the ACTUAL
# collectible integration node set of this directory (excluding this guard
# module itself) in BOTH directions. A renamed/removed real test, or a
# manifest entry with no corresponding real test, fails loudly here — the
# completeness guard is only trustworthy if its SSOT tracks the real suite.
# --------------------------------------------------------------------------- #
def test_manifest_matches_actual_collectible_set_both_directions() -> None:
    # `--collect-only` still runs `pytest_sessionfinish`, so if this child
    # inherited an armed `SAENA_MEASUREMENT_FAILURE_REQUIRED` from the parent
    # process (e.g. when the whole suite itself runs under the required gate)
    # the completeness guard would hard-fail a collect-only run that executes
    # nothing — an unrelated false-fire. Strip it explicitly, same discipline
    # as the coverage-matrix meta-test's own child subprocess.
    env = dict(os.environ)
    env.pop(_REQUIRED_ENV_VAR, None)
    # Also strip any inherited PYTEST_ADDOPTS `-k` — it would narrow the
    # collect-only set and break the drift equality (defense vs a poisoned parent
    # env; the real gate clears PYTEST_ADDOPTS anyway).
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            str(_THIS_DIR),
            "-m",
            "integration",
            "--ignore",
            str(_THIS_DIR / "test_failure_required_guard.py"),
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"collect-only itself failed:\n{combined}"

    collected: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        # collect-only -q emits bare node-id lines (no leading whitespace in
        # the default short format); normalize any absolute/relative prefix
        # the same way the guard's own `_norm` does.
        collected.add(_failure_complete._norm(line))

    manifest = _failure_complete.EXPECTED_NODE_IDS
    missing_from_manifest = collected - manifest
    missing_from_suite = manifest - collected

    assert not missing_from_manifest, (
        "test(s) exist in the real suite but are ABSENT from the "
        "_failure_completeness manifest (a new/renamed test the manifest must "
        f"be updated to include):\n{sorted(missing_from_manifest)}\n\nfull "
        f"collect-only output:\n{combined}"
    )
    assert not missing_from_suite, (
        "manifest entry/entries do NOT correspond to any real collectible test "
        "(a removed/renamed test the manifest still references — stale SSOT):\n"
        f"{sorted(missing_from_suite)}\n\nfull collect-only output:\n{combined}"
    )

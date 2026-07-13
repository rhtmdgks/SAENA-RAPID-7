"""Self-verifying proof for the zero-collected HARD FAILURE guard (c5-01).

The guard (in this directory's `conftest.py::pytest_collection_finish`) hard-
fails the required real-container measurement E2E lane (`pytest.UsageError` ->
exit 4, non-zero/non-5) — instead of pytest's silently-tolerated exit-5 "no
tests collected" — when the EXPLICIT env-var contract
`SAENA_MEASUREMENT_E2E_REQUIRED=1` is set AND zero items were collected FROM
THIS DIRECTORY. That flag is set only by the c5-05 required named-gate recipe
(`just measurement-e2e`); umbrella / dev / broad `tests/integration` runs never
set it, so 0-here is silent in those (no false-fire on an ancestor/umbrella
invocation).

These tests PROVE the four required behaviours by running pytest AS A
SUBPROCESS (the guard aborts the whole session, so it cannot be exercised
in-process) with `SAENA_MEASUREMENT_E2E_REQUIRED` set/unset in the subprocess
env:

  (a) flag set + `-k` deselecting everything  -> exit 4 + guard message
  (b) flag set + a normal non-empty selection -> passes, guard silent
  (c) flag NOT set + zero-collected-here       -> guard silent (pins MF-2 dead:
      no false-fire on an umbrella/ancestor invocation that collects nothing
      here)
  (d) Docker-absent + flag set                 -> items still COLLECT (>0) so
      the guard is silent; the container tests skip individually

A dedicated inert `test_*` leaf (`test_inert_leaf_for_nonempty_selection_
proof`) is the single-item selection target for (b), so nesting stays exactly
one level deep with no self-matching `-k` recursion.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_GUARD_FILE = _THIS_DIR / "test_zero_collected_guard.py"

_REQUIRED_ENV_VAR = "SAENA_MEASUREMENT_E2E_REQUIRED"

#: A `-k` expression guaranteed to match none of this directory's tests — used
#: to force an empty selection, the exact condition the guard must hard-fail on
#: WHEN the env-var contract is armed.
_NO_MATCH_K_EXPR = "this_k_expression_matches_no_test_whatsoever_c5e2e"

#: pytest's exit code for a `pytest.UsageError` (what the guard raises).
_EXPECTED_USAGE_ERROR_EXIT = 4
#: pytest's exit code for "no tests collected" — the tolerated default the
#: guard exists to REPLACE with a hard failure.
_TOLERATED_NO_TESTS_EXIT = 5


def _run_pytest_subprocess(
    args: list[str], *, required_flag: bool
) -> subprocess.CompletedProcess[str]:
    """Run pytest as a subprocess with `SAENA_MEASUREMENT_E2E_REQUIRED`
    explicitly set to "1" (armed) or removed (disarmed) in the child env — the
    parent's own value never leaks in, so each scenario controls the contract
    deterministically."""
    env = dict(os.environ)
    if required_flag:
        env[_REQUIRED_ENV_VAR] = "1"
    else:
        env.pop(_REQUIRED_ENV_VAR, None)
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", *args, "-p", "no:cacheprovider", "-q"],
        capture_output=True,
        text=True,
        cwd=str(_THIS_DIR),
        env=env,
    )


def test_inert_leaf_for_nonempty_selection_proof() -> None:
    """An intentionally trivial, side-effect-free leaf used ONLY as the
    single-item selection target of scenario (b) below — it spawns no further
    subprocess, so selecting it keeps the nesting depth bounded (one level)."""
    assert True


# --------------------------------------------------------------------------- #
# (a) flag SET + a `-k` that deselects everything -> exit 4 + guard message.
# --------------------------------------------------------------------------- #
def test_a_flag_set_zero_collected_hard_fails_non5() -> None:
    result = _run_pytest_subprocess([str(_THIS_DIR), "-k", _NO_MATCH_K_EXPR], required_flag=True)
    combined = result.stdout + result.stderr

    assert result.returncode == _EXPECTED_USAGE_ERROR_EXIT, (
        "zero-collected guard did not hard-fail as a UsageError "
        f"(expected exit {_EXPECTED_USAGE_ERROR_EXIT}, got {result.returncode}). "
        f"Output:\n{combined}"
    )
    assert result.returncode not in (0, _TOLERATED_NO_TESTS_EXIT), (
        "zero-collected guard degraded to a silent pass (0) or pytest's "
        f"tolerated exit-5; got {result.returncode}:\n{combined}"
    )
    assert "collected ZERO test items" in combined, (
        f"guard message absent from subprocess output:\n{combined}"
    )
    assert f"{_REQUIRED_ENV_VAR}=1" in combined, (
        f"guard message should name the env-var contract that armed it; output:\n{combined}"
    )


# --------------------------------------------------------------------------- #
# (b) flag SET + a normal non-empty selection -> passes, guard silent.
# --------------------------------------------------------------------------- #
def test_b_flag_set_nonempty_selection_passes_guard_silent() -> None:
    target_node = f"{_GUARD_FILE}::test_inert_leaf_for_nonempty_selection_proof"
    result = _run_pytest_subprocess([target_node], required_flag=True)
    combined = result.stdout + result.stderr

    assert "collected ZERO test items" not in combined, (
        f"guard spuriously fired on a NON-empty selection with the flag set:\n{combined}"
    )
    assert result.returncode == 0, (
        "a non-empty selection with the flag set must pass cleanly (guard "
        f"silent); got exit {result.returncode}:\n{combined}"
    )


# --------------------------------------------------------------------------- #
# (c) flag NOT set + zero-collected-here -> guard silent (MF-2 pinned dead:
#     an umbrella/ancestor invocation that collects nothing HERE must NOT
#     hard-fail the whole suite).
# --------------------------------------------------------------------------- #
def test_c_flag_unset_zero_collected_here_does_not_false_fire() -> None:
    # Force a zero-from-this-dir selection (the `-k` no-match) WITHOUT the flag
    # — exactly the shape an umbrella run past this lane, or a
    # `pytest tests/integration -k <sibling-test>` ancestor run, produces for
    # this directory. The guard must stay silent: pytest's own bare exit-5
    # ("no tests collected") is the correct, non-hard-failing outcome here.
    result = _run_pytest_subprocess([str(_THIS_DIR), "-k", _NO_MATCH_K_EXPR], required_flag=False)
    combined = result.stdout + result.stderr

    assert "collected ZERO test items" not in combined, (
        "guard FALSE-FIRED without the env-var contract set — an umbrella / "
        f"ancestor invocation must never hard-fail this lane:\n{combined}"
    )
    assert result.returncode != _EXPECTED_USAGE_ERROR_EXIT, (
        "guard raised UsageError (exit 4) without the env-var contract set — "
        f"this is the MF-2 false-fire that must stay dead:\n{combined}"
    )
    # pytest's own tolerated "no tests collected" exit-5 is the expected,
    # non-hard-failing outcome for a disarmed empty selection.
    assert result.returncode == _TOLERATED_NO_TESTS_EXIT, (
        "a disarmed zero-collected selection should fall through to pytest's "
        f"own exit-5, not a hard failure; got {result.returncode}:\n{combined}"
    )


# --------------------------------------------------------------------------- #
# (d) Docker-absent + flag SET -> items still COLLECT (>0), guard silent, the
#     container tests skip individually.
# --------------------------------------------------------------------------- #
def test_d_docker_absent_flag_set_items_collect_guard_silent() -> None:
    # Simulate a Docker-absent host by pointing DOCKER_HOST at an unreachable
    # address IN THE CHILD ENV, with the required flag armed. The container
    # tests must still be COLLECTED (then individually skipped), so the count
    # FROM THIS DIRECTORY is > 0 and the guard stays silent — a zero-collected
    # hard failure must never be conflated with an honest Docker-absent skip.
    env = dict(os.environ)
    env[_REQUIRED_ENV_VAR] = "1"
    env["DOCKER_HOST"] = "tcp://127.0.0.1:1"
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            str(_THIS_DIR),
            "-m",
            "integration",
            # Deselect this guard file's OWN subprocess-spawning tests so the
            # child run does not recurse; the real-container tests + the inert
            # leaf still collect, proving "items collect > 0" under the flag.
            "-k",
            "not test_a_ and not test_b_ and not test_c_ and not test_d_",
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(_THIS_DIR),
        env=env,
    )
    combined = result.stdout + result.stderr

    assert "collected ZERO test items" not in combined, (
        "guard hard-failed on a Docker-absent host despite the flag being set "
        "— items must still COLLECT (and skip individually), never be treated "
        f"as zero-collected:\n{combined}"
    )
    assert result.returncode != _EXPECTED_USAGE_ERROR_EXIT, (
        "guard raised UsageError on a Docker-absent host — an honest skip must "
        f"never be conflated with zero-collected:\n{combined}"
    )
    assert result.returncode == 0, (
        "Docker-absent + flag set should exit 0 (items collected then honestly "
        f"skipped), not a hard failure; got {result.returncode}:\n{combined}"
    )
    assert "skipped" in combined, (
        f"expected the real-container items to be honestly skipped:\n{combined}"
    )

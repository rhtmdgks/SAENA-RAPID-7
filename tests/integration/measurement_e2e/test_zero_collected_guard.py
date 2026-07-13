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

These tests PROVE the required behaviours by running pytest AS A SUBPROCESS
(the guard aborts the whole session, so it cannot be exercised in-process) with
`SAENA_MEASUREMENT_E2E_REQUIRED` set/unset in the subprocess env:

  (a) flag set + `-k` deselecting everything  -> exit 4 (UsageError) + message
      (the ZERO-COLLECTED guard in `pytest_collection_finish`)
  (b) flag set + a selection keeping ONLY container-free items (the inert guard
      leaf) -> HARD FAILURE exit 6 (critic-F probe 5a: a required run that
      executes ZERO real-container scenarios is a BYPASS — collection_finish
      stays silent because dir items DO exist, so `pytest_sessionfinish` must
      catch the empty real-container set). Was previously (wrongly) asserted as
      an exit-0 pass; the corrected fail-closed contract forbids that.
  (c) flag NOT set + zero-collected-here       -> guard silent (MF-2 dead: no
      false-fire on an umbrella/ancestor invocation collecting nothing here)
  (d) flag set + Docker absent (infra-absent → real-container scenarios all
      SKIP) -> HARD FAILURE exit 6 (the required-mode no-skip guard in
      `pytest_sessionfinish`; MUST-FIX A — a required lane must never pass as
      "0 passed, N skipped"). Docker absence subsumes ClickHouse/Temporal
      absence + any missing runtime dependency (all surface as skips).
  (e) flag NOT set + Docker absent             -> documented honest skip, exit 0
  (f) flag set + a single required container test still skips -> HARD FAILURE
      exit 6 (ONE un-run scenario is enough; not only the all-skipped case)

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
# (b) flag SET + a selection keeping ONLY container-free items (the inert guard
#     leaf) -> HARD FAILURE exit 6. Critic-F probe 5a regression: dir items DO
#     exist (so `pytest_collection_finish`'s zero-DIR-collected UsageError stays
#     silent — no false-fire), but ZERO real-container scenarios were selected,
#     which `pytest_sessionfinish` must reject as a required-lane BYPASS. A
#     required run that executes no Postgres/ClickHouse/Temporal scenario at all
#     must never pass green.
# --------------------------------------------------------------------------- #
def test_b_flag_set_container_free_only_selection_hard_fails_bypass_closed() -> None:
    target_node = f"{_GUARD_FILE}::test_inert_leaf_for_nonempty_selection_proof"
    result = _run_pytest_subprocess([target_node], required_flag=True)
    combined = result.stdout + result.stderr

    assert "collected ZERO test items" not in combined, (
        "the zero-DIR-collected guard must stay silent here (dir items DO "
        f"exist) — the BYPASS is caught by pytest_sessionfinish instead:\n{combined}"
    )
    assert result.returncode == _EXPECTED_INFRA_HARD_FAIL_EXIT, (
        "arming the required flag then selecting ONLY container-free tests must "
        "HARD FAIL (exit 6) — a required run that executes zero real-container "
        f"scenarios is a bypass, never a green pass; got exit {result.returncode}:\n{combined}"
    )
    assert result.returncode not in (0, _TOLERATED_NO_TESTS_EXIT), (
        "the container-free-only bypass degraded to a silent pass (0) or "
        f"tolerated exit-5; got {result.returncode}:\n{combined}"
    )
    assert "HARD FAILURE" in combined, (
        f"expected the required-mode guard's reason message:\n{combined}"
    )
    assert "ZERO real-container" in combined, (
        f"expected the bypass-specific reason (zero real-container selected):\n{combined}"
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


# The required-mode all-skipped / infra-absent HARD-FAILURE exit code
# (session.exitstatus set in conftest.pytest_sessionfinish). Distinct from
# UsageError(4) and no-tests(5).
_EXPECTED_INFRA_HARD_FAIL_EXIT = 6


# A `-k` clause that ALWAYS excludes this guard file's own subprocess-spawning
# tests so a child run can never recurse. Callers AND it with their own filter.
_NO_RECURSE = (
    "not test_a_ and not test_b_ and not test_c_ and not test_d_ "
    "and not test_e_ and not test_f_ and not test_g_ and not test_inert_"
)


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


# --------------------------------------------------------------------------- #
# (d) REQUIRED + Docker absent -> HARD FAILURE (MUST-FIX A). The real-container
#     scenarios are collected then individually skipped; a required lane must
#     NEVER pass as "0 passed, N skipped". Docker absence subsumes ClickHouse/
#     Temporal absence and any missing-runtime-dependency path — they ALL
#     surface as skips, which this same guard turns into a non-zero exit.
# --------------------------------------------------------------------------- #
def test_d_required_docker_absent_hard_fails_non_zero() -> None:
    result = _run_child(required_flag=True, docker_absent=True)
    combined = result.stdout + result.stderr
    assert result.returncode not in (0, _TOLERATED_NO_TESTS_EXIT), (
        "REQUIRED lane with Docker absent must HARD FAIL (non-zero, non-5) — a "
        "required real-container lane must never pass as '0 passed, N skipped'; "
        f"got exit {result.returncode}:\n{combined}"
    )
    assert result.returncode == _EXPECTED_INFRA_HARD_FAIL_EXIT, (
        f"expected the infra-absent hard-fail exit {_EXPECTED_INFRA_HARD_FAIL_EXIT}; "
        f"got {result.returncode}:\n{combined}"
    )
    assert "HARD FAILURE" in combined, f"expected the guard's reason message:\n{combined}"


# --------------------------------------------------------------------------- #
# (e) OPTIONAL (flag unset) + Docker absent -> documented honest skip, exit 0.
# --------------------------------------------------------------------------- #
def test_e_optional_docker_absent_is_an_honest_skip() -> None:
    result = _run_child(required_flag=False, docker_absent=True)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        "OPTIONAL lane (no SAENA_MEASUREMENT_E2E_REQUIRED) with Docker absent must "
        f"be a documented honest skip, exit 0; got {result.returncode}:\n{combined}"
    )
    assert "skipped" in combined, f"expected honest skips in optional mode:\n{combined}"
    assert "HARD FAILURE" not in combined, (
        f"the required-mode guard must NOT fire when the flag is unset:\n{combined}"
    )


# --------------------------------------------------------------------------- #
# (f) REQUIRED + exactly ONE required container test forced to skip (the rest
#     could run) -> HARD FAILURE. Proves the guard fails on a PARTIAL skip, not
#     only the all-skipped case. Injected via a `-k` that also excludes one
#     real-container test AND a `--runxfail`-style deselection is NOT used
#     (deselection != skip); instead we point DOCKER_HOST at an unreachable
#     address so the container tests skip, which is the realistic partial-skip
#     shape a required lane must reject — combined with a selection narrowed to
#     a single container test proves ONE skip is enough to hard-fail.
# --------------------------------------------------------------------------- #
def test_f_required_single_container_test_skipped_hard_fails() -> None:
    result = _run_child(
        required_flag=True,
        docker_absent=True,
        k_extra="test_full_pass_flow_b_verified_skill_intake_accepted",
    )
    combined = result.stdout + result.stderr
    # With Docker absent, even a single selected container test skips -> the
    # guard hard-fails; a required lane never tolerates a single un-run scenario.
    assert result.returncode == _EXPECTED_INFRA_HARD_FAIL_EXIT, (
        "a single skipped required container test must hard-fail the lane; got "
        f"exit {result.returncode}:\n{combined}"
    )


# --------------------------------------------------------------------------- #
# (g) REQUIRED armed with a NON-canonical truthy value (`true` / `yes` / `" 1 "`
#     with whitespace) -> still ARMS (critic-F SHOULD-FIX: fail-safe arming, not
#     exact `== "1"` equality). Docker absent + `true` => still HARD FAIL exit 6.
#     A typo must never silently downgrade the required lane to optional/skip.
# --------------------------------------------------------------------------- #
def test_g_required_arms_on_non_canonical_truthy_value() -> None:
    for value in ("true", "yes", " 1 "):
        result = _run_child(required_flag=True, docker_absent=True, required_value=value)
        combined = result.stdout + result.stderr
        assert result.returncode == _EXPECTED_INFRA_HARD_FAIL_EXIT, (
            f"{_REQUIRED_ENV_VAR}={value!r} must still ARM the required lane "
            f"(fail-safe), hard-failing exit {_EXPECTED_INFRA_HARD_FAIL_EXIT} when "
            f"Docker absent; got {result.returncode}:\n{combined}"
        )
        assert "HARD FAILURE" in combined, (
            f"expected the required-mode guard message for value {value!r}:\n{combined}"
        )

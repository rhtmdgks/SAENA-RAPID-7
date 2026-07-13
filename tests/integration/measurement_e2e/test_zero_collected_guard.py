"""Self-verifying proof for the zero-collected HARD FAILURE guard (c5-01 MF-1).

The critic's MUST-FIX: the required real-container measurement E2E lane must
FAIL (non-zero, non-5 exit) — never silently exit 5 — when this directory is
an explicit invocation target yet ZERO test items are collected from it (a
naming typo, a `-k`/`-m` mismatch, or an import/collection error). A CI
wrapper that tolerates pytest's bare exit-5 would otherwise see this lane
contribute nothing while appearing green.

This test PROVES the guard fires by running pytest AS A SUBPROCESS against this
very directory with a `-k` filter that matches nothing, and asserting:
  * the exit code is 4 (`pytest.UsageError`) — NOT 0 (silent pass) and NOT 5
    (the tolerated "no tests collected" pytest default the guard replaces);
  * the guard's own message text is present in the output.

It is NOT marked `@pytest.mark.integration` — it needs no Docker/ClickHouse/
Temporal, only a Python interpreter — so it runs (and the guard is proven) on
EVERY host, including the Docker-absent ones where every real container test
here is honestly skipped. A subprocess is used deliberately: the guard is a
`pytest_collection_finish` hook that aborts the WHOLE session, so it cannot be
exercised in-process without aborting the very session running this test.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

#: A `-k` expression guaranteed to match none of this directory's tests — used
#: to force an empty selection of a DELIBERATELY-targeted invocation of this
#: directory, the exact condition the guard must hard-fail on.
_NO_MATCH_K_EXPR = "this_k_expression_matches_no_test_whatsoever_c5e2e"

#: pytest's exit code for a `pytest.UsageError` (what the guard raises).
_EXPECTED_USAGE_ERROR_EXIT = 4
#: pytest's exit code for "no tests collected" — the tolerated default the
#: guard exists to REPLACE with a hard failure.
_TOLERATED_NO_TESTS_EXIT = 5


def test_inert_leaf_for_nonempty_selection_proof() -> None:
    """An intentionally trivial, side-effect-free leaf used ONLY as the
    single-item selection target of
    `test_guard_stays_silent_on_nonempty_selection_of_this_dir`'s subprocess —
    it spawns no further subprocess, so selecting it keeps the nesting depth
    bounded (guard-silent proof runs one level deep, no recursion)."""
    assert True


def test_zero_collected_targeting_this_dir_hard_fails_non5() -> None:
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            str(_THIS_DIR),
            "-k",
            _NO_MATCH_K_EXPR,
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(_THIS_DIR),
    )
    combined_output = result.stdout + result.stderr

    assert result.returncode == _EXPECTED_USAGE_ERROR_EXIT, (
        "zero-collected guard did not hard-fail as a UsageError "
        f"(expected exit {_EXPECTED_USAGE_ERROR_EXIT}, got {result.returncode}). "
        f"Output:\n{combined_output}"
    )
    assert result.returncode != 0, "zero-collected must never be a silent pass"
    assert result.returncode != _TOLERATED_NO_TESTS_EXIT, (
        "zero-collected guard degraded back to pytest's tolerated exit-5 "
        "'no tests collected' — the whole point of the guard is to NOT exit 5"
    )
    assert "collected ZERO test items" in combined_output, (
        "the zero-collected guard message is absent from the subprocess output; "
        f"got:\n{combined_output}"
    )


def test_guard_stays_silent_on_nonempty_selection_of_this_dir() -> None:
    """The guard must trip ONLY on a ZERO-item selection, never on a non-empty
    one. Run pytest as a subprocess selecting exactly ONE real item from this
    directory — the always-collectable `test_zero_collected_targeting_this_dir_
    hard_fails_non5` node above (chosen because it is NOT
    `@pytest.mark.integration`, so it is neither skipped on a Docker-absent
    host nor itself a container test) — and assert the guard stays silent.

    The selection target is `test_inert_leaf_for_nonempty_selection_proof`
    (a trivial `assert True` leaf that spawns NO subprocess), chosen by EXACT
    node id so nesting stays exactly one level deep — no self-matching `-k`
    filter that could recurse.
    """
    target_node = (
        f"{_THIS_DIR / 'test_zero_collected_guard.py'}"
        "::test_inert_leaf_for_nonempty_selection_proof"
    )
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            target_node,
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(_THIS_DIR),
    )
    combined_output = result.stdout + result.stderr
    assert "collected ZERO test items" not in combined_output, (
        "guard spuriously fired on a NON-empty (single-item) selection of this "
        f"directory; output:\n{combined_output}"
    )
    assert result.returncode == 0, (
        "a non-empty selection of this directory must pass cleanly (guard "
        f"silent); got exit {result.returncode}:\n{combined_output}"
    )

"""META module (container-free): the required-scenario completeness SSOT drift
test + subprocess self-tests proving the required-mode guard has teeth.

This module is listed in ``_e2e_manifest.META_MODULES`` and is therefore EXEMPT
from the required-scenario accounting — it proves the guard, it is not a
scenario. It needs only a Python interpreter (no real customer repo, no Docker),
so it runs on every host including the required lane.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from _e2e_manifest import (
    DUMP_ENV_VAR,
    EXPECTED_SCENARIO_IDS,
    META_MODULES,
    REQUIRED_ENV_VAR,
    REQUIRED_SCENARIOS,
    evaluate,
    is_meta_node,
    scenario_for_node,
)

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[2]
_E2E_TARGET = "tests/e2e/pilot"


def _run_pytest(
    args: list[str], *, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != REQUIRED_ENV_VAR}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(  # noqa: S603 — list argv, never shell
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )


# --------------------------------------------------------------------------- #
# Drift: manifest set == collected scenario set, BOTH directions.
# --------------------------------------------------------------------------- #
def test_manifest_matches_collected_scenarios_both_directions(tmp_path: Path) -> None:
    dump = tmp_path / "collected.json"
    result = _run_pytest(
        ["--collect-only", "-q", _E2E_TARGET],
        env_extra={DUMP_ENV_VAR: str(dump)},
    )
    assert result.returncode == 0, f"collect-only failed:\n{result.stdout}\n{result.stderr}"
    collected = json.loads(dump.read_text(encoding="utf-8"))
    assert collected, "collect-only produced no node ids"

    non_meta = [n for n in collected if not is_meta_node(n)]
    orphans = [n for n in non_meta if scenario_for_node(n) is None]
    assert not orphans, f"non-meta tests match no manifest scenario (orphans): {orphans}"

    covered = {scenario_for_node(n) for n in non_meta}
    # BOTH directions: no manifest scenario without a test, no test scenario
    # missing from the manifest.
    assert covered == set(EXPECTED_SCENARIO_IDS), (
        f"manifest/collected drift: only-in-manifest={set(EXPECTED_SCENARIO_IDS) - covered}, "
        f"only-in-suite={covered - set(EXPECTED_SCENARIO_IDS)}"
    )
    # The meta module IS collected (and excluded), never silently dropped.
    assert any(is_meta_node(n) for n in collected)


def test_suite_has_at_least_forty_scenario_tests(tmp_path: Path) -> None:
    dump = tmp_path / "collected.json"
    result = _run_pytest(
        ["--collect-only", "-q", _E2E_TARGET],
        env_extra={DUMP_ENV_VAR: str(dump)},
    )
    assert result.returncode == 0, result.stderr
    collected = json.loads(dump.read_text(encoding="utf-8"))
    scenario_tests = [n for n in collected if not is_meta_node(n) and scenario_for_node(n)]
    assert len(scenario_tests) >= 40, f"only {len(scenario_tests)} scenario tests (need >=40)"


# --------------------------------------------------------------------------- #
# Guard teeth (subprocess, collection-level).
# --------------------------------------------------------------------------- #
def test_armed_zero_collected_exits_nonzero(tmp_path: Path) -> None:
    result = _run_pytest(
        [_E2E_TARGET, "-k", "zzz_no_such_test_matches_this"],
        env_extra={REQUIRED_ENV_VAR: "1"},
    )
    assert result.returncode != 0
    assert "ZERO test items" in (result.stdout + result.stderr)


def test_armed_partial_selection_exits_nonzero(tmp_path: Path) -> None:
    # Selecting only ONE scenario while armed must fail at collection — the
    # partial-selection fail-open the manifest exists to close.
    result = _run_pytest(
        [_E2E_TARGET, "-k", "nextjs_audit"],
        env_extra={REQUIRED_ENV_VAR: "1"},
    )
    assert result.returncode != 0
    assert "do not cover the required-scenario manifest" in (result.stdout + result.stderr)


def test_unarmed_partial_selection_is_allowed(tmp_path: Path) -> None:
    # WITHOUT arming, a partial selection is a normal honest local run: it
    # collects fine (proven via collect-only to stay cheap).
    result = _run_pytest([_E2E_TARGET, "-k", "nextjs_audit", "--collect-only", "-q"])
    assert result.returncode == 0, result.stderr


def test_arming_is_fail_safe(tmp_path: Path) -> None:
    # A typo'd truthy value ("true"/"yes") must still ARM (fail-safe), so a
    # partial selection still fails.
    for value in ("true", "yes", " 1 "):
        result = _run_pytest(
            [_E2E_TARGET, "-k", "nextjs_audit"],
            env_extra={REQUIRED_ENV_VAR: value},
        )
        assert result.returncode != 0, f"{value!r} should arm the guard"
    # …while an explicit disable does NOT arm.
    result = _run_pytest(
        [_E2E_TARGET, "-k", "nextjs_audit", "--collect-only", "-q"],
        env_extra={REQUIRED_ENV_VAR: "0"},
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# Guard decision logic (in-process): evaluate() has teeth.
# --------------------------------------------------------------------------- #
def _node(key: str, detail: str = "x") -> str:
    return f"{_E2E_TARGET}/test_x.py::test_{key}__{detail}"


def _all_pass_nodes() -> dict[str, str]:
    return {s.scenario_id: _node(s.key) for s in REQUIRED_SCENARIOS}


def test_evaluate_ok_when_every_scenario_passes() -> None:
    nodes = _all_pass_nodes()
    collected = set(nodes.values())
    report = evaluate(collected=collected, passed=collected, skipped=set(), failed=set())
    assert report.ok, report.reasons
    assert report.satisfied == EXPECTED_SCENARIO_IDS


def test_evaluate_flags_missing_scenario() -> None:
    nodes = _all_pass_nodes()
    dropped = next(iter(nodes))  # drop one scenario entirely
    collected = {v for k, v in nodes.items() if k != dropped}
    report = evaluate(collected=collected, passed=collected, skipped=set(), failed=set())
    assert not report.ok
    assert dropped in report.missing_scenarios


def test_evaluate_flags_skipped_scenario() -> None:
    nodes = _all_pass_nodes()
    collected = set(nodes.values())
    one = next(iter(nodes.values()))
    report = evaluate(collected=collected, passed=collected - {one}, skipped={one}, failed=set())
    assert not report.ok
    assert any("skipped" in r or "did not execute-and-PASS" in r for r in report.reasons)


def test_evaluate_flags_failed_scenario() -> None:
    nodes = _all_pass_nodes()
    collected = set(nodes.values())
    one = next(iter(nodes.values()))
    report = evaluate(collected=collected, passed=collected - {one}, skipped=set(), failed={one})
    assert not report.ok


def test_evaluate_flags_orphan_test() -> None:
    nodes = _all_pass_nodes()
    orphan = f"{_E2E_TARGET}/test_x.py::test_not_a_scenario__oops"
    collected = set(nodes.values()) | {orphan}
    report = evaluate(collected=collected, passed=collected, skipped=set(), failed=set())
    assert not report.ok
    assert orphan in report.orphans


def test_meta_module_names_are_recognized() -> None:
    assert "test_completeness_guard.py" in META_MODULES
    assert is_meta_node(f"{_E2E_TARGET}/test_completeness_guard.py::test_whatever")
    assert not is_meta_node(f"{_E2E_TARGET}/test_frameworks.py::test_nextjs_audit__x")

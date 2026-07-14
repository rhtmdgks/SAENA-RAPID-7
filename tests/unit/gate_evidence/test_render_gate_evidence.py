"""Unit tests for the fail-closed measurement-gate evidence renderer.

Target under test: ``tools/validation/render_gate_evidence.py`` — ``render()``
and ``main()``. These tests are pure JSON-fixture tests (no Docker, no
network, no real gate execution): every fixture is a hand-built dict written
to ``tmp_path`` that mimics the shape ``tests/integration/_gate_evidence.py``
(the writer) produces, pinned to the same ``SCHEMA_VERSION``.

Each test asserts the exact exit code (``0`` == PROVEN, non-zero == fail
closed) `render()`/`main()` returns for one specific evidence shape, per the
renderer's fail-closed contract: any of missing file / unreadable / malformed
JSON / non-dict / schema mismatch / gate_name mismatch / no run_binding /
stale commit_sha / stale github_run_id / required_mode_armed false /
completeness_passed false / non-empty missing_node_ids / non-zero
skipped_count / non-zero failed_count / real_containers_proven false / any
required leg missing a witness or with 0 passed / non-positive expected_count
must fail closed (non-zero). Only a fully-complete, real-container, passing
evidence dict returns 0.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

# --------------------------------------------------------------------------- #
# Robust import of the module under test (it lives outside any package with
# an __init__.py chain reachable from here, so we load it directly by path).
# --------------------------------------------------------------------------- #
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODULE_PATH = _REPO_ROOT / "tools" / "validation" / "render_gate_evidence.py"

_spec = importlib.util.spec_from_file_location("render_gate_evidence", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
render_gate_evidence = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = render_gate_evidence
_spec.loader.exec_module(render_gate_evidence)

render = render_gate_evidence.render
main = render_gate_evidence.main
SCHEMA_VERSION = render_gate_evidence.SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Fixture builders — mirror tests/integration/_gate_evidence.py's shape.
# --------------------------------------------------------------------------- #
def _leg(*, witness: bool = True, passed: int = 3, executed: int = 3) -> dict[str, Any]:
    return {"executed": executed, "passed": passed, "witness": witness}


def _run_binding(*, commit_sha: str = "deadbeef", github_run_id: str = "12345") -> dict[str, Any]:
    return {
        "commit_sha": commit_sha,
        "github_run_id": github_run_id,
        "github_run_attempt": "1",
        "invocation_id": "test-invocation",
    }


def _witnesses(legs: tuple[str, ...]) -> dict[str, Any]:
    return {leg: {"image": f"{leg}:test-image"} for leg in legs}


def complete_e2e_evidence(**overrides: Any) -> dict[str, Any]:
    legs = ("postgres", "clickhouse", "temporal")
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "gate_name": "e2e",
        "run_binding": _run_binding(),
        "required_mode_armed": True,
        "completeness_passed": True,
        "expected_count": 5,
        "selected_count": 5,
        "executed_count": 5,
        "passed_count": 5,
        "failed_count": 0,
        "skipped_count": 0,
        "xfailed_count": 0,
        "xpassed_count": 0,
        "deselected_count": 0,
        "missing_node_ids": [],
        "unexpected_node_ids": [],
        "duplicate_ids": [],
        "legs": {leg: _leg() for leg in legs},
        "real_containers_proven": True,
        "witnesses": _witnesses(legs),
    }
    data.update(overrides)
    return data


def complete_failure_modes_evidence(**overrides: Any) -> dict[str, Any]:
    legs = ("postgres",)
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "gate_name": "failure-modes",
        "run_binding": _run_binding(),
        "required_mode_armed": True,
        "completeness_passed": True,
        "expected_count": 9,
        "selected_count": 9,
        "executed_count": 9,
        "passed_count": 9,
        "failed_count": 0,
        "skipped_count": 0,
        "xfailed_count": 0,
        "xpassed_count": 0,
        "deselected_count": 0,
        "missing_node_ids": [],
        "unexpected_node_ids": [],
        "duplicate_ids": [],
        "legs": {leg: _leg() for leg in legs},
        "real_containers_proven": True,
        "witnesses": _witnesses(legs),
        "primary_expected": 5,
        "primary_executed": 5,
        "primary_passed": 5,
        "recovery_expected": 4,
        "recovery_executed": 4,
        "recovery_passed": 4,
    }
    data.update(overrides)
    return data


def _write(tmp_path: Path, data: dict[str, Any], name: str = "evidence.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    return path


# --------------------------------------------------------------------------- #
# 1. Valid complete E2E evidence -> exit 0, markdown contains "PROVEN".
# --------------------------------------------------------------------------- #
def test_complete_e2e_evidence_passes(tmp_path: Path) -> None:
    path = _write(tmp_path, complete_e2e_evidence())
    code, markdown = render("e2e", path)
    assert code == 0
    assert "PROVEN" in markdown


# --------------------------------------------------------------------------- #
# 2. Valid complete failure-modes evidence -> exit 0.
# --------------------------------------------------------------------------- #
def test_complete_failure_modes_evidence_passes(tmp_path: Path) -> None:
    path = _write(tmp_path, complete_failure_modes_evidence())
    code, markdown = render("failure-modes", path)
    assert code == 0
    assert "PROVEN" in markdown


# --------------------------------------------------------------------------- #
# 3. Missing file -> non-0, "does not exist".
# --------------------------------------------------------------------------- #
def test_missing_evidence_file_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "does-not-exist.json"
    code, markdown = render("e2e", path)
    assert code != 0
    assert "does not exist" in markdown


# --------------------------------------------------------------------------- #
# 4. Malformed JSON -> non-0.
# --------------------------------------------------------------------------- #
def test_malformed_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_text("{not valid json,,,")
    code, markdown = render("e2e", path)
    assert code != 0
    assert "not valid JSON" in markdown or "malformed" in markdown


# --------------------------------------------------------------------------- #
# 5. Not a JSON object (e.g. a list) -> non-0.
# --------------------------------------------------------------------------- #
def test_non_object_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps([1, 2, 3]))
    code, markdown = render("e2e", path)
    assert code != 0
    assert "not a JSON object" in markdown


# --------------------------------------------------------------------------- #
# 6. schema_version mismatch -> non-0.
# --------------------------------------------------------------------------- #
def test_schema_version_mismatch_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence(schema_version="saena.gate-evidence/v0")
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "schema_version" in markdown


# --------------------------------------------------------------------------- #
# 7. gate_name mismatch (evidence says e2e, asked failure-modes) -> non-0.
# --------------------------------------------------------------------------- #
def test_gate_name_mismatch_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence()  # gate_name == "e2e"
    path = _write(tmp_path, data)
    code, markdown = render("failure-modes", path)
    assert code != 0
    assert "gate_name" in markdown


# --------------------------------------------------------------------------- #
# 8. Stale commit_sha -> non-0 "stale".
# --------------------------------------------------------------------------- #
def test_stale_commit_sha_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", "current-sha-X")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    data = complete_e2e_evidence(run_binding=_run_binding(commit_sha="stale-sha-Y"))
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "stale" in markdown


# --------------------------------------------------------------------------- #
# 9. Stale github_run_id -> non-0.
# --------------------------------------------------------------------------- #
def test_stale_github_run_id_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setenv("GITHUB_RUN_ID", "current-run-999")
    data = complete_e2e_evidence(run_binding=_run_binding(github_run_id="stale-run-111"))
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "stale" in markdown


# --------------------------------------------------------------------------- #
# 10. required_mode_armed false -> non-0.
# --------------------------------------------------------------------------- #
def test_required_mode_not_armed_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence(required_mode_armed=False)
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "armed" in markdown


# --------------------------------------------------------------------------- #
# 11. completeness_passed false -> non-0.
# --------------------------------------------------------------------------- #
def test_completeness_not_passed_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence(completeness_passed=False)
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "completeness_passed" in markdown


# --------------------------------------------------------------------------- #
# 12. missing_node_ids non-empty -> non-0.
# --------------------------------------------------------------------------- #
def test_missing_node_ids_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence(missing_node_ids=["tests/e2e/test_x.py::test_y"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "required node(s) did not execute-and-PASS" in markdown


# --------------------------------------------------------------------------- #
# 13. skipped_count=1 -> non-0.
# --------------------------------------------------------------------------- #
def test_skipped_count_nonzero_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence(skipped_count=1)
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "skipped_count=1" in markdown


# --------------------------------------------------------------------------- #
# 14. failed_count=1 -> non-0.
# --------------------------------------------------------------------------- #
def test_failed_count_nonzero_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence(failed_count=1)
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "failed_count=1" in markdown


# --------------------------------------------------------------------------- #
# 15. real_containers_proven false -> non-0.
# --------------------------------------------------------------------------- #
def test_real_containers_not_proven_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence(real_containers_proven=False)
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "real_containers_proven" in markdown


# --------------------------------------------------------------------------- #
# 16. e2e evidence missing the temporal leg witness -> non-0.
# --------------------------------------------------------------------------- #
def test_missing_temporal_leg_witness_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence()
    data["legs"] = copy.deepcopy(data["legs"])
    data["legs"]["temporal"]["witness"] = False
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "no real-container witness for the 'temporal' leg" in markdown


# --------------------------------------------------------------------------- #
# 17. e2e leg present but passed=0 -> non-0.
# --------------------------------------------------------------------------- #
def test_leg_present_but_zero_passed_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence()
    data["legs"] = copy.deepcopy(data["legs"])
    data["legs"]["postgres"]["passed"] = 0
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "zero passing tests on the 'postgres' leg" in markdown


# --------------------------------------------------------------------------- #
# 18. expected_count=0 (empty manifest) -> non-0.
# --------------------------------------------------------------------------- #
def test_zero_expected_count_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence(expected_count=0)
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "expected_count is 0" in markdown


# --------------------------------------------------------------------------- #
# 19. No GITHUB_SHA/RUN_ID in env (local dev) + otherwise-complete evidence
#     -> exit 0 (binding check skipped locally).
# --------------------------------------------------------------------------- #
def test_local_dev_without_ci_env_still_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    # Evidence's own run_binding need not match anything real in this mode.
    data = complete_e2e_evidence(
        run_binding=_run_binding(commit_sha="local-sha", github_run_id="0")
    )
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code == 0
    assert "PROVEN" in markdown


# --------------------------------------------------------------------------- #
# 20. main([...]) writes the markdown to --summary-file and returns the same
#     code.
# --------------------------------------------------------------------------- #
def test_main_writes_summary_file_and_returns_matching_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    evidence_path = _write(tmp_path, complete_e2e_evidence())
    summary_path = tmp_path / "summary.md"

    expected_code, expected_markdown = render("e2e", evidence_path)

    code = main(
        [
            "--gate",
            "e2e",
            "--evidence",
            str(evidence_path),
            "--summary-file",
            str(summary_path),
        ]
    )

    assert code == expected_code
    assert code == 0
    written = summary_path.read_text()
    assert expected_markdown in written
    assert "PROVEN" in written


def test_main_writes_summary_file_on_failure_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    evidence_path = tmp_path / "missing.json"
    summary_path = tmp_path / "summary.md"

    code = main(
        [
            "--gate",
            "e2e",
            "--evidence",
            str(evidence_path),
            "--summary-file",
            str(summary_path),
        ]
    )

    assert code != 0
    written = summary_path.read_text()
    assert "does not exist" in written

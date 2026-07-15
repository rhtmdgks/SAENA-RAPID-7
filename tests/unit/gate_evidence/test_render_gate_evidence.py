"""Unit tests for the STRICT fail-closed measurement-gate evidence renderer.

Target under test: ``tools/validation/render_gate_evidence.py`` — ``render()``
and ``main()``. These tests are pure JSON-fixture tests (no Docker, no
network, no real gate execution): every fixture is a hand-built dict that
mirrors the EXACT payload shape ``tests/integration/_gate_evidence.py`` (the
writer, ``write_evidence``/``record_container_witness``) and the two
``build_evidence_payload`` functions (``tests/integration/
_measurement_e2e_completeness.py`` and ``tests/integration/measurement_failure/
_failure_completeness.py``) produce, validated against the authoritative
``gate_evidence_spec.SPEC`` (expected_count=28 e2e / 31 failure-modes, exact
per-leg counts, required witness legs, container-id-required legs, and the
authorized-unexpected-file allowlist).

One test per invariant; each asserts the EXACT exit code ``render()`` returns
for one specific evidence shape/mutation. Only a fully self-consistent,
real-container, fully-passing, correctly-bound payload returns 0 (PROVEN).
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
# It imports `gate_evidence_spec` relative to its own directory via sys.path,
# so that directory must be importable BEFORE exec_module runs.
# --------------------------------------------------------------------------- #
_REPO_ROOT = Path(__file__).resolve().parents[3]
_VALIDATION_DIR = _REPO_ROOT / "tools" / "validation"
_MODULE_PATH = _VALIDATION_DIR / "render_gate_evidence.py"

if str(_VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(_VALIDATION_DIR))

_spec = importlib.util.spec_from_file_location("render_gate_evidence", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
render_gate_evidence = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = render_gate_evidence
_spec.loader.exec_module(render_gate_evidence)

render = render_gate_evidence.render
main = render_gate_evidence.main
SCHEMA_VERSION = render_gate_evidence.SCHEMA_VERSION

from gate_evidence_spec import SPEC  # noqa: E402

_E2E_SPEC = SPEC["e2e"]
_FAIL_SPEC = SPEC["failure-modes"]

_BINDING_VARS = (
    "GITHUB_SHA",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
    "SAENA_GATE_INVOCATION_ID",
)


@pytest.fixture(autouse=True)
def _no_binding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear all four binding env vars by default so a test asserting a
    specific fail-closed reason is not preempted by the binding check (and so
    this suite is deterministic whether it runs locally or inside real CI,
    which always sets GITHUB_SHA/RUN_ID/RUN_ATTEMPT). Valid-render tests set
    matching env explicitly; binding-mutation tests set mismatched env
    explicitly. Both override this fixture within their own test."""
    for var in _BINDING_VARS:
        monkeypatch.delenv(var, raising=False)


def _set_matching_binding_env(monkeypatch: pytest.MonkeyPatch, binding: dict[str, Any]) -> None:
    monkeypatch.setenv("GITHUB_SHA", binding["commit_sha"])
    monkeypatch.setenv("GITHUB_RUN_ID", binding["github_run_id"])
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", binding["github_run_attempt"])
    monkeypatch.setenv("SAENA_GATE_INVOCATION_ID", binding["invocation_id"])


# --------------------------------------------------------------------------- #
# Fixture builders — mirror the EXACT shape of
# tests/integration/_gate_evidence.py's write_evidence()/record_container_
# witness() and the two build_evidence_payload() functions.
# --------------------------------------------------------------------------- #
def _run_binding(
    *,
    commit_sha: str = "sha-A",
    github_run_id: str = "run-A",
    github_run_attempt: str = "1",
    invocation_id: str = "inv-A",
) -> dict[str, Any]:
    return {
        "commit_sha": commit_sha,
        "github_run_id": github_run_id,
        "github_run_attempt": github_run_attempt,
        "invocation_id": invocation_id,
    }


def _witness(
    leg: str,
    *,
    image: str,
    container_id: str | None,
    started: Any = True,
) -> dict[str, Any]:
    return {
        "leg": leg,
        "image": image,
        "container_id": container_id,
        "detail": None,
        "started": started,
    }


def _e2e_witnesses() -> dict[str, Any]:
    return {
        "postgres": _witness("postgres", image="postgres:16-alpine", container_id="abc123def456"),
        "clickhouse": _witness(
            "clickhouse",
            image="clickhouse/clickhouse-server:24.8-alpine",
            container_id="beefcafe1234",
        ),
        "temporal": _witness(
            "temporal", image="temporalio-time-skipping-test-server", container_id=None
        ),
    }


def _failure_witnesses() -> dict[str, Any]:
    return {
        "postgres": _witness("postgres", image="postgres:16-alpine", container_id="abc123def456"),
    }


_E2E_AUTHORIZED_FILE = _E2E_SPEC.authorized_unexpected_files[0]
_FAIL_AUTHORIZED_FILE = _FAIL_SPEC.authorized_unexpected_files[0]


def complete_e2e_evidence(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "gate_name": "e2e",
        "run_binding": _run_binding(),
        "required_mode_armed": True,
        "command_started": True,
        "collection_completed": True,
        "completeness_passed": True,
        "exit_code": 0,
        "expected_count": _E2E_SPEC.expected_count,
        "selected_count": _E2E_SPEC.expected_count,
        "executed_count": _E2E_SPEC.expected_count,
        "passed_count": _E2E_SPEC.expected_count,
        "failed_count": 0,
        "skipped_count": 0,
        "xfailed_count": 0,
        "xpassed_count": 0,
        "deselected_count": 0,
        "missing_node_ids": [],
        "unexpected_node_ids": [
            f"{_E2E_AUTHORIZED_FILE}::test_a_zero_collected_guard_meta",
        ],
        "duplicate_ids": [],
        "legs": {
            "postgres": {"executed": 19, "passed": 19, "witness": True},
            "clickhouse": {"executed": 19, "passed": 19, "witness": True},
            "composed": {"executed": 19, "passed": 19, "witness": True},
            "temporal": {"executed": 9, "passed": 9, "witness": True},
        },
        "real_containers_proven": True,
        "witnesses": _e2e_witnesses(),
    }
    data.update(overrides)
    return data


def complete_failure_modes_evidence(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "gate_name": "failure-modes",
        "run_binding": _run_binding(),
        "required_mode_armed": True,
        "command_started": True,
        "collection_completed": True,
        "completeness_passed": True,
        "exit_code": 0,
        "expected_count": _FAIL_SPEC.expected_count,
        "selected_count": _FAIL_SPEC.expected_count,
        "executed_count": _FAIL_SPEC.expected_count,
        "passed_count": _FAIL_SPEC.expected_count,
        "failed_count": 0,
        "skipped_count": 0,
        "xfailed_count": 0,
        "xpassed_count": 0,
        "deselected_count": 0,
        "missing_node_ids": [],
        "unexpected_node_ids": [
            f"{_FAIL_AUTHORIZED_FILE}::test_a_failure_required_guard_meta",
        ],
        "duplicate_ids": [],
        "legs": {
            "postgres": {"executed": 31, "passed": 31, "witness": True},
        },
        "real_containers_proven": True,
        "witnesses": _failure_witnesses(),
        "primary_expected": 16,
        "primary_executed": 16,
        "primary_passed": 16,
        "recovery_expected": 15,
        "recovery_executed": 15,
        "recovery_passed": 15,
        "postgres_scenarios": 31,
    }
    data.update(overrides)
    return data


def _write(tmp_path: Path, data: dict[str, Any], name: str = "evidence.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    return path


def _deep_leg_override(data: dict[str, Any], leg: str, **leg_overrides: Any) -> dict[str, Any]:
    data = copy.deepcopy(data)
    data["legs"][leg].update(leg_overrides)
    return data


def _deep_witness_override(data: dict[str, Any], leg: str, **w_overrides: Any) -> dict[str, Any]:
    data = copy.deepcopy(data)
    data["witnesses"][leg].update(w_overrides)
    return data


# =========================================================================== #
# 1. Valid complete E2E evidence -> exit 0, PROVEN.
# =========================================================================== #
def test_01_valid_e2e_evidence_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = complete_e2e_evidence()
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code == 0
    assert "PROVEN" in markdown


# =========================================================================== #
# 2. Valid complete failure-modes evidence -> exit 0, PROVEN.
# =========================================================================== #
def test_02_valid_failure_modes_evidence_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_failure_modes_evidence()
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("failure-modes", path)
    assert code == 0
    assert "PROVEN" in markdown


# =========================================================================== #
# 3. command_started false -> non-zero.
# =========================================================================== #
def test_03_command_started_false_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(command_started=False)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "command_started" in markdown


# =========================================================================== #
# 4a. command_started missing (key absent) -> non-zero.
# =========================================================================== #
def test_04a_command_started_missing_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence()
    del data["command_started"]
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, _markdown = render("e2e", path)
    assert code != 0


# =========================================================================== #
# 4b. command_started null -> non-zero.
# =========================================================================== #
def test_04b_command_started_null_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(command_started=None)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, _markdown = render("e2e", path)
    assert code != 0


# =========================================================================== #
# 4c. command_started string "true" -> non-zero (strict `is True`, no truthy).
# =========================================================================== #
def test_04c_command_started_string_true_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(command_started="true")
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, _markdown = render("e2e", path)
    assert code != 0


# =========================================================================== #
# 5. collection_completed false -> non-zero.
# =========================================================================== #
def test_05_collection_completed_false_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(collection_completed=False)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "collection_completed" in markdown


# =========================================================================== #
# 6. exit_code=6 even with completeness_passed=true -> non-zero (never trust
#    completeness_passed alone; exit_code must independently be 0).
# =========================================================================== #
def test_06_nonzero_exit_code_with_completeness_true_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(exit_code=6, completeness_passed=True)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "exit_code" in markdown


# =========================================================================== #
# 7. expected_count/selected_count mismatch -> non-zero.
# =========================================================================== #
def test_07_expected_selected_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(selected_count=27)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "selected_count" in markdown


# =========================================================================== #
# 8. expected_count/executed_count mismatch -> non-zero.
# =========================================================================== #
def test_08_expected_executed_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(executed_count=27)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "executed_count" in markdown


# =========================================================================== #
# 9. expected_count/passed_count mismatch -> non-zero.
# =========================================================================== #
def test_09_expected_passed_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(passed_count=27)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "passed_count" in markdown


# =========================================================================== #
# 10. passed_count > executed_count (relational belt-and-suspenders) ->
#     non-zero. (Also independently a passed_count!=expected mismatch, but the
#     relational message must appear too.)
# =========================================================================== #
def test_10_passed_greater_than_executed_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(executed_count=20, passed_count=28)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "passed_count=28 > executed_count=20" in markdown


# =========================================================================== #
# 11. executed_count > selected_count -> non-zero.
# =========================================================================== #
def test_11_executed_greater_than_selected_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(selected_count=20)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "executed_count=28 > selected_count=20" in markdown


# =========================================================================== #
# 12. failed_count > 0 -> non-zero.
# =========================================================================== #
def test_12_failed_count_nonzero_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(failed_count=1)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "failed_count=1" in markdown


# =========================================================================== #
# 13. skipped_count > 0 -> non-zero.
# =========================================================================== #
def test_13_skipped_count_nonzero_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(skipped_count=1)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "skipped_count=1" in markdown


# =========================================================================== #
# 14. xfailed_count > 0 -> non-zero.
# =========================================================================== #
def test_14_xfailed_count_nonzero_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(xfailed_count=1)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "xfailed_count=1" in markdown


# =========================================================================== #
# 15. xpassed_count > 0 -> non-zero.
# =========================================================================== #
def test_15_xpassed_count_nonzero_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(xpassed_count=1)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "xpassed_count=1" in markdown


# =========================================================================== #
# 16. deselected_count > 0 -> non-zero.
# =========================================================================== #
def test_16_deselected_count_nonzero_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(deselected_count=1)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "deselected_count=1" in markdown


# =========================================================================== #
# 17. missing_node_ids non-empty -> non-zero.
# =========================================================================== #
def test_17_missing_node_ids_nonempty_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(
        missing_node_ids=["tests/integration/measurement_e2e/test_x.py::test_y"]
    )
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "missing_node_ids" in markdown


# =========================================================================== #
# 18. duplicate_ids non-empty -> non-zero.
# =========================================================================== #
def test_18_duplicate_ids_nonempty_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(
        duplicate_ids=["tests/integration/measurement_e2e/test_x.py::test_y"]
    )
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "duplicate_ids" in markdown


# =========================================================================== #
# 19. unauthorized unexpected node (from a non-authorized file) -> non-zero.
# =========================================================================== #
def test_19_unauthorized_unexpected_node_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(
        unexpected_node_ids=["tests/integration/measurement_e2e/test_not_authorized.py::test_z"]
    )
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "unauthorized unexpected node" in markdown


# =========================================================================== #
# 20. authorized guard/meta nodes present in unexpected_node_ids -> still 0.
# =========================================================================== #
def test_20_authorized_unexpected_nodes_still_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(
        unexpected_node_ids=[
            f"{_E2E_AUTHORIZED_FILE}::test_a",
            f"{_E2E_AUTHORIZED_FILE}::test_b",
        ]
    )
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code == 0
    assert "PROVEN" in markdown


# =========================================================================== #
# 21. missing leg (leg key absent from legs block) -> non-zero.
# =========================================================================== #
def test_21_missing_leg_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = complete_e2e_evidence()
    del data["legs"]["temporal"]
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "temporal" in markdown


# =========================================================================== #
# 22. leg count mismatch (executed != authoritative spec count) -> non-zero.
# =========================================================================== #
def test_22_leg_count_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _deep_leg_override(complete_e2e_evidence(), "postgres", executed=18)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "legs['postgres'].executed" in markdown


# =========================================================================== #
# 23. witness missing (no runtime witness object for a required leg) ->
#     non-zero.
# =========================================================================== #
def test_23_witness_missing_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = complete_e2e_evidence()
    del data["witnesses"]["temporal"]
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "no runtime witness object for the 'temporal' leg" in markdown


# =========================================================================== #
# 24. witness started=false -> non-zero.
# =========================================================================== #
def test_24_witness_started_false_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _deep_witness_override(complete_e2e_evidence(), "postgres", started=False)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "witness 'postgres'.started is not the boolean True" in markdown


# =========================================================================== #
# 25. witness started="true" (string, not bool) -> non-zero.
# =========================================================================== #
def test_25_witness_started_string_true_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _deep_witness_override(complete_e2e_evidence(), "postgres", started="true")
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "witness 'postgres'.started is not the boolean True" in markdown


# =========================================================================== #
# 26. empty image -> non-zero.
# =========================================================================== #
def test_26_empty_witness_image_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _deep_witness_override(complete_e2e_evidence(), "postgres", image="")
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "witness 'postgres'.image is empty/absent" in markdown


# =========================================================================== #
# 27. empty/invalid container_id for postgres -> non-zero.
# =========================================================================== #
def test_27_invalid_container_id_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _deep_witness_override(complete_e2e_evidence(), "postgres", container_id="")
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "witness 'postgres'.container_id" in markdown


# =========================================================================== #
# 28. witness leg/key mismatch -> non-zero.
# =========================================================================== #
def test_28_witness_leg_key_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = copy.deepcopy(complete_e2e_evidence())
    data["witnesses"]["postgres"]["leg"] = "clickhouse"
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "leg/key mismatch" in markdown


# =========================================================================== #
# 29. primary/recovery mismatch (failure gate) -> non-zero.
# =========================================================================== #
def test_29_primary_recovery_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_failure_modes_evidence(primary_expected=15)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("failure-modes", path)
    assert code != 0
    assert "primary_expected" in markdown


# =========================================================================== #
# 30. Stale SHA -> non-zero.
# =========================================================================== #
def test_30_stale_sha_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = complete_e2e_evidence()
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    monkeypatch.setenv("GITHUB_SHA", "sha-DIFFERENT")
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "stale" in markdown


# =========================================================================== #
# 31. Stale run id -> non-zero.
# =========================================================================== #
def test_31_stale_run_id_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = complete_e2e_evidence()
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    monkeypatch.setenv("GITHUB_RUN_ID", "run-DIFFERENT")
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "stale" in markdown


# =========================================================================== #
# 32. Stale run attempt -> non-zero.
# =========================================================================== #
def test_32_stale_run_attempt_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = complete_e2e_evidence()
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "stale" in markdown


# =========================================================================== #
# 33. Stale invocation id with same SHA/run -> non-zero.
# =========================================================================== #
def test_33_stale_invocation_id_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence()
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    monkeypatch.setenv("SAENA_GATE_INVOCATION_ID", "inv-DIFFERENT")
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "stale" in markdown


# =========================================================================== #
# 34. Invocation env missing while an expected invocation id was supplied via
#     another binding var (CI mode: every field required once any is
#     expected) -> non-zero.
# =========================================================================== #
def test_34_invocation_missing_while_expected_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence()
    binding = dict(data["run_binding"])
    del binding["invocation_id"]
    data["run_binding"] = binding
    monkeypatch.setenv("GITHUB_SHA", "sha-A")
    monkeypatch.setenv("GITHUB_RUN_ID", "run-A")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("SAENA_GATE_INVOCATION_ID", "inv-A")
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "invocation_id" in markdown


# =========================================================================== #
# 35. Malformed JSON -> non-zero.
# =========================================================================== #
def test_35_malformed_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_text("{not valid json,,,")
    code, markdown = render("e2e", path)
    assert code != 0
    assert "not valid JSON" in markdown or "malformed" in markdown


# =========================================================================== #
# 36. Wrong schema_version -> non-zero.
# =========================================================================== #
def test_36_wrong_schema_version_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(schema_version="saena.gate-evidence/v0")
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "schema_version" in markdown


# =========================================================================== #
# 37. Missing evidence file -> non-zero.
# =========================================================================== #
def test_37_missing_evidence_file_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "does-not-exist.json"
    code, markdown = render("e2e", path)
    assert code != 0
    assert "does not exist" in markdown


# =========================================================================== #
# 38. Pre-planted, internally-consistent evidence from a PRIOR invocation
#     (matching SHA/run but different invocation_id) -> non-zero (replay
#     protection — an attacker cannot pre-generate a valid-looking file and
#     replay it across invocations of the same commit+run).
# =========================================================================== #
def test_38_replayed_prior_invocation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(run_binding=_run_binding(invocation_id="inv-OLD"))
    monkeypatch.setenv("GITHUB_SHA", "sha-A")
    monkeypatch.setenv("GITHUB_RUN_ID", "run-A")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("SAENA_GATE_INVOCATION_ID", "inv-NEW")
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "stale" in markdown


# =========================================================================== #
# 39. No binding env supplied at all (fully unbound) -> non-zero ("refusing to
#     render PROVEN unbound").
# =========================================================================== #
def test_39_no_binding_env_unbound_fails_closed(tmp_path: Path) -> None:
    data = complete_e2e_evidence()
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "unbound" in markdown


# =========================================================================== #
# 40. Valid render reflects real facts: markdown contains PROVEN + the actual
#     counts (not merely a code==0 assertion).
# =========================================================================== #
def test_40_valid_render_reflects_real_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence()
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code == 0
    assert "PROVEN" in markdown
    assert "expected=28" in markdown
    assert "selected=28" in markdown
    assert "executed=28" in markdown
    assert "passed=28" in markdown
    assert "failed=0" in markdown
    assert "skipped=0" in markdown
    assert "missing=0" in markdown


# =========================================================================== #
# Type-strictness tests.
# =========================================================================== #
def test_41_exit_code_bool_true_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(exit_code=True)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "exit_code" in markdown


def test_42_passed_count_bool_true_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(passed_count=True)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "passed_count" in markdown


def test_43_expected_count_float_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(expected_count=28.0)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "expected_count" in markdown


def test_44_expected_count_string_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(expected_count="28")
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "expected_count" in markdown


def test_45_negative_count_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = complete_e2e_evidence(failed_count=-1)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "failed_count" in markdown


# =========================================================================== #
# Additional structural / lifecycle invariants not in the explicit mission
# numbering but exercised by the strict validator.
# =========================================================================== #
def test_46_gate_name_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence()  # gate_name == "e2e"
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("failure-modes", path)
    assert code != 0
    assert "gate_name" in markdown


def test_47_non_object_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps([1, 2, 3]))
    code, markdown = render("e2e", path)
    assert code != 0
    assert "not a JSON object" in markdown


def test_48_required_mode_not_armed_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(required_mode_armed=False)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "required_mode_armed" in markdown


def test_49_completeness_passed_false_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(completeness_passed=False)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "completeness_passed" in markdown


def test_50_real_containers_not_proven_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(real_containers_proven=False)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "real_containers_proven" in markdown


def test_51_composed_leg_not_backed_by_real_witness_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence()
    del data["witnesses"]["clickhouse"]
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "'composed' leg not backed by a real 'clickhouse' witness" in markdown


def test_52_witness_image_wrong_family_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _deep_witness_override(complete_e2e_evidence(), "postgres", image="mysql:8")
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "not in the approved family" in markdown


def test_53_zero_expected_count_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence(
        expected_count=0,
        selected_count=0,
        executed_count=0,
        passed_count=0,
    )
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "expected_count" in markdown


def test_54_leg_witness_false_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _deep_leg_override(complete_e2e_evidence(), "temporal", witness=False)
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "legs['temporal'].witness is not True" in markdown


def test_55_main_writes_summary_file_and_returns_matching_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence()
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    evidence_path = _write(tmp_path, data)
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


def test_56_main_writes_summary_file_on_failure_too(tmp_path: Path) -> None:
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


# =========================================================================== #
# Unknown-key rejection (critic-A/C MUST-FIX): a fabricated EXTRA leg or witness
# key injected alongside all valid required data must fail closed — the legs /
# witnesses blocks must be EXACTLY the authoritative set, never a superset.
# =========================================================================== #
def test_unknown_extra_leg_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence()
    data["legs"]["fake_extra_leg"] = {"executed": 1, "passed": 1, "witness": True}
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "fabricated leg" in markdown or "unexpected/fabricated leg" in markdown


def test_unknown_extra_witness_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_e2e_evidence()
    data["witnesses"]["redis"] = {
        "leg": "redis",
        "image": "redis:7",
        "container_id": "abcdef123456",
        "detail": None,
        "started": True,
    }
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, markdown = render("e2e", path)
    assert code != 0
    assert "fabricated witness" in markdown or "unexpected/fabricated witness" in markdown


def test_unknown_extra_leg_fails_closed_failure_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = complete_failure_modes_evidence()
    data["legs"]["fake_extra_leg"] = {"executed": 1, "passed": 1, "witness": True}
    _set_matching_binding_env(monkeypatch, data["run_binding"])
    path = _write(tmp_path, data)
    code, _markdown = render("failure-modes", path)
    assert code != 0

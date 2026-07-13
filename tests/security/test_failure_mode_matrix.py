"""Completeness gate for `failure_mode_matrix.json` (testing-strategy.md sec
F-8: "failure-mode 9종(k3s §10) ↔ `tests/security` fixture 1:1 매핑 표 —
runner GA 게이트").

This is the CI-blocking test: if a failure mode's fixture/test entry is ever
removed from `failure_mode_matrix.json` (or a referenced test function is
ever deleted/renamed without updating the matrix), THIS test fails —
"so CI blocks if a mode loses its fixture" (mission instruction).

Deliberately AST-based (not a dynamic `importlib` import) for resolving
`"path/to/test_module.py::test_name"` references: several referenced
modules (the `tests/integration/failure_modes/**` ones) require a reachable
Docker daemon / a real Postgres testcontainer to actually EXECUTE, but this
completeness check must stay green (and FAST) even when Docker is
unavailable — it only needs to prove the referenced test function is
DEFINED, not that it currently passes (each mode's own test file is
independently responsible for actually passing).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MATRIX_PATH = Path(__file__).resolve().parent / "failure_mode_matrix.json"

_EXPECTED_MODE_IDS = tuple(f"F-{n}" for n in range(1, 10))

_REQUIRED_MODE_KEYS = frozenset(
    {
        "id",
        "name",
        "fixture",
        "injection_point",
        "expected_state_transition",
        "expected_event",
        "expected_audit_record",
        "retryable",
        "rollback_required",
        "operator_visible_error",
        "redaction_verified",
        "partial_state_absent",
        "recovery_test",
        "test",
        "wired_against",
    }
)

# `pytest::node::id[param0]` parametrize-instance suffix — the underlying
# function is still named without it in the module's own AST.
_PARAM_SUFFIX_RE = re.compile(r"\[[^\]]*\]$")


def _load_matrix() -> dict[str, Any]:
    return json.loads(_MATRIX_PATH.read_text())


def _module_function_names(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(), filename=str(module_path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _assert_test_node_exists(node_id: str) -> None:
    assert "::" in node_id, f"not a 'path::function' test node id: {node_id!r}"
    module_part, function_part = node_id.split("::", 1)
    function_name = _PARAM_SUFFIX_RE.sub("", function_part)

    module_path = _REPO_ROOT / module_part
    assert module_path.is_file(), f"referenced test module does not exist: {module_part!r}"

    function_names = _module_function_names(module_path)
    assert function_name in function_names, (
        f"referenced test function {function_name!r} not found in {module_part!r} "
        f"(available: {sorted(function_names)!r})"
    )


def test_matrix_file_exists_and_is_valid_json() -> None:
    assert _MATRIX_PATH.is_file()
    matrix = _load_matrix()
    assert "modes" in matrix
    assert isinstance(matrix["modes"], list)


def test_matrix_has_exactly_the_9_authoritative_failure_modes_no_gaps() -> None:
    matrix = _load_matrix()
    mode_ids = [mode["id"] for mode in matrix["modes"]]

    assert len(mode_ids) == 9, (
        f"expected exactly 9 failure modes, found {len(mode_ids)}: {mode_ids}"
    )
    assert len(set(mode_ids)) == 9, f"duplicate failure-mode id(s) in matrix: {mode_ids}"
    assert set(mode_ids) == set(_EXPECTED_MODE_IDS), (
        f"failure-mode id set mismatch — expected {_EXPECTED_MODE_IDS}, got {tuple(mode_ids)}"
    )
    assert mode_ids == list(_EXPECTED_MODE_IDS), (
        "failure modes must be listed F-1..F-9 in order (matrix readability)"
    )


def test_every_mode_carries_every_required_field_non_empty() -> None:
    matrix = _load_matrix()
    for mode in matrix["modes"]:
        missing = _REQUIRED_MODE_KEYS - set(mode.keys())
        assert not missing, f"{mode.get('id', '<unknown>')} is missing field(s): {sorted(missing)}"
        for key in ("id", "name", "fixture", "test", "recovery_test"):
            assert mode[key], f"{mode.get('id', '<unknown>')}.{key} must not be empty"
        assert isinstance(mode["wired_against"], list) and mode["wired_against"], (
            f"{mode['id']}.wired_against must be a non-empty list — every mode must be wired "
            "against real code, not left abstract"
        )


def test_every_modes_primary_and_recovery_test_actually_exists() -> None:
    matrix = _load_matrix()
    for mode in matrix["modes"]:
        _assert_test_node_exists(mode["test"])
        _assert_test_node_exists(mode["recovery_test"])
        # complementary_tests (optional; F-5 lists the retained contract_hash
        # defense) must also resolve if present — no dangling references.
        for node in mode.get("complementary_tests", []):
            _assert_test_node_exists(node)


def test_rollback_verification_gate_section_is_present_and_every_listed_test_exists() -> None:
    matrix = _load_matrix()
    rollback_gate = matrix.get("rollback_verification_gate")
    assert rollback_gate is not None, "matrix is missing the rollback_verification_gate section"

    required_properties = {
        "patch-unit rollback leaves no partial commit",
        "failed-worktree cleanup",
        "workflow retry/replay",
        "duplicate-event dedup",
        "outbox replay",
        "approval-ledger immutability",
        "artifact immutability",
        "audit-chain preservation",
        "tenant isolation on rollback",
        "main/source repo unchanged after rollback",
    }
    covered = set(rollback_gate["properties_covered"])
    missing_properties = required_properties - covered
    assert not missing_properties, f"rollback gate missing propert(y/ies): {missing_properties}"

    test_nodes = rollback_gate["tests"]
    assert test_nodes, "rollback_verification_gate.tests must not be empty"
    for node_id in test_nodes:
        _assert_test_node_exists(node_id)


def test_no_test_security_python_module_is_left_out_of_every_matrix_reference() -> None:
    """A softer completeness check in the OTHER direction: every
    `test_f*.py`/`test_rollback_*.py` module under this directory
    contributes at least one node referenced somewhere in the matrix — a
    new failure-mode/rollback test file added here without ever being
    wired into the matrix would otherwise go unnoticed."""
    matrix = _load_matrix()
    referenced_modules = {
        node_id.split("::", 1)[0]
        for mode in matrix["modes"]
        for node_id in (mode["test"], mode["recovery_test"])
    }
    referenced_modules |= {
        node_id.split("::", 1)[0]
        for mode in matrix["modes"]
        for node_id in mode.get("complementary_tests", [])
    }
    referenced_modules |= {
        node_id.split("::", 1)[0] for node_id in matrix["rollback_verification_gate"]["tests"]
    }

    this_dir = Path(__file__).resolve().parent
    fixture_modules = sorted(
        f"tests/security/{p.name}"
        for p in this_dir.glob("test_*.py")
        if p.name not in {"test_failure_mode_matrix.py"}
    )
    unreferenced = [m for m in fixture_modules if m not in referenced_modules]
    assert not unreferenced, f"module(s) not referenced anywhere in the matrix: {unreferenced}"

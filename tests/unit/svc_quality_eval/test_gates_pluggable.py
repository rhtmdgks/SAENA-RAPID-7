"""Pluggable gate tests (mission item 3): schema/contract validation,
lint/typecheck/unit/integration/boundary, plus `commit_coherence` (mission
item 1's base/target coherence check as an independently-reportable gate)."""

from __future__ import annotations

from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gates import (
    gate_boundary,
    gate_commit_coherence,
    gate_integration_tests,
    gate_lint,
    gate_schema_contract,
    gate_typecheck,
    gate_unit_tests,
)
from saena_quality_eval.inputs import (
    BoundaryOutcome,
    LintOutcome,
    SchemaContractOutcome,
    TestOutcome,
    TypecheckOutcome,
)


def test_commit_coherence_gate_passes_when_bases_match() -> None:
    result = gate_commit_coherence(approved_base_commit="a" * 40, artifact_base_commit="a" * 40)
    assert result.passed is True
    assert result.gate_id == GateId.COMMIT_COHERENCE


def test_commit_coherence_gate_fails_on_base_target_mismatch() -> None:
    """Explicit negative/edge test: base/target commit mismatch."""
    result = gate_commit_coherence(approved_base_commit="a" * 40, artifact_base_commit="f" * 40)
    assert result.passed is False
    assert result.failures[0].error_code == "saena.validation.base_commit_mismatch"
    assert result.failures[0].redacted_detail["expected_base_commit"] == "a" * 40
    assert result.failures[0].redacted_detail["actual_base_commit"] == "f" * 40


def test_schema_contract_gate_passes_when_valid() -> None:
    assert gate_schema_contract(SchemaContractOutcome(valid=True)).passed is True


def test_schema_contract_gate_fails_when_invalid() -> None:
    outcome = SchemaContractOutcome(valid=False, invalid_contract_ids=("change-plan",))
    assert gate_schema_contract(outcome).passed is False


def test_lint_gate_passes_with_zero_violations() -> None:
    assert gate_lint(LintOutcome(tool="ruff", violation_count=0)).passed is True


def test_lint_gate_fails_on_violations() -> None:
    result = gate_lint(LintOutcome(tool="ruff", violation_count=3, sample_violations=("F401",)))
    assert result.passed is False


def test_typecheck_gate_passes_with_zero_errors() -> None:
    assert gate_typecheck(TypecheckOutcome(tool="mypy", error_count=0)).passed is True


def test_typecheck_gate_fails_on_errors() -> None:
    result = gate_typecheck(TypecheckOutcome(tool="mypy", error_count=2))
    assert result.passed is False


def test_unit_tests_gate_passes_and_fails_independently_of_integration() -> None:
    passing = TestOutcome(suite="unit", total=5, passed=5, failed=0)
    assert gate_unit_tests(passing).passed is True
    assert gate_unit_tests(passing).gate_id == GateId.UNIT_TESTS

    failing = TestOutcome(suite="unit", total=5, passed=4, failed=1)
    assert gate_unit_tests(failing).passed is False


def test_integration_tests_gate_passes_and_fails() -> None:
    passing = TestOutcome(suite="integration", total=3, passed=3, failed=0)
    assert gate_integration_tests(passing).passed is True
    assert gate_integration_tests(passing).gate_id == GateId.INTEGRATION_TESTS

    failing = TestOutcome(suite="integration", total=3, passed=2, failed=1)
    assert gate_integration_tests(failing).passed is False


def test_boundary_gate_passes_when_all_files_in_scope() -> None:
    outcome = BoundaryOutcome(
        changed_files=("apps/web/a.py",), approved_scope_globs=("apps/web/*",)
    )
    assert gate_boundary(outcome).passed is True


def test_boundary_gate_fails_on_out_of_scope_file() -> None:
    outcome = BoundaryOutcome(
        changed_files=("apps/web/a.py", "services/other/b.py"),
        approved_scope_globs=("apps/web/*",),
        out_of_scope_files=("services/other/b.py",),
    )
    result = gate_boundary(outcome)
    assert result.passed is False
    assert "services/other/b.py" in result.failures[0].redacted_detail["out_of_scope_files"]

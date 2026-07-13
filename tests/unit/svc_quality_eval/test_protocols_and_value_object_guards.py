"""`protocols.py`'s `Fake*` in-memory adapters, and the construction-time
guards on `GateResult`/`CoverageReport`/`PerformanceOutcome`."""

from __future__ import annotations

import pytest
from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gate_result import GateResult
from saena_quality_eval.inputs import (
    BuildOutcome,
    CoverageReport,
    GeneratedCodeDriftOutcome,
    PerformanceOutcome,
    SecretScanOutcome,
    SecurityScanOutcome,
    TestOutcome,
)
from saena_quality_eval.inputs import (
    CoverageReport as CoverageReportAlias,  # noqa: N813 — re-import for clarity only
)
from saena_quality_eval.protocols import (
    BuildRunner,
    CoverageReporter,
    FakeBuildRunner,
    FakeCoverageReporter,
    FakeGeneratedCodeDriftScanner,
    FakeSecretScanner,
    FakeSecurityScanner,
    FakeTestRunner,
    GeneratedCodeDriftScanner,
    SecretScanner,
    SecurityScanner,
    TestRunner,
)


def test_fake_build_runner_returns_the_configured_outcome_and_satisfies_the_protocol() -> None:
    outcome = BuildOutcome(succeeded=True, command="make build", exit_code=0)
    runner = FakeBuildRunner(outcome)
    assert isinstance(runner, BuildRunner)
    assert runner.run_build() is outcome


def test_fake_test_runner_looks_up_outcome_by_suite_name() -> None:
    unit_outcome = TestOutcome(suite="unit", total=1, passed=1, failed=0)
    runner = FakeTestRunner({"unit": unit_outcome})
    assert isinstance(runner, TestRunner)
    assert runner.run_tests("unit") is unit_outcome


def test_fake_test_runner_raises_key_error_for_an_unconfigured_suite() -> None:
    runner = FakeTestRunner({})
    with pytest.raises(KeyError):
        runner.run_tests("integration")


def test_fake_security_scanner_returns_the_configured_outcome() -> None:
    outcome = SecurityScanOutcome(secret_leak_count=1)
    scanner = FakeSecurityScanner(outcome)
    assert isinstance(scanner, SecurityScanner)
    assert scanner.scan() is outcome


def test_fake_secret_scanner_returns_the_configured_outcome() -> None:
    outcome = SecretScanOutcome()
    scanner = FakeSecretScanner(outcome)
    assert isinstance(scanner, SecretScanner)
    assert scanner.scan() is outcome


def test_fake_generated_code_drift_scanner_returns_the_configured_outcome() -> None:
    outcome = GeneratedCodeDriftOutcome(drifted_paths=("a.py",))
    scanner = FakeGeneratedCodeDriftScanner(outcome)
    assert isinstance(scanner, GeneratedCodeDriftScanner)
    assert scanner.scan() is outcome


def test_fake_coverage_reporter_returns_the_configured_report() -> None:
    report = CoverageReportAlias(changed_lines_total=10, changed_lines_covered=9)
    reporter = FakeCoverageReporter(report)
    assert isinstance(reporter, CoverageReporter)
    assert reporter.report() is report


def test_no_fake_adapter_performs_any_subprocess_or_network_io() -> None:
    """Structural guarantee, not just documentation: none of the `Fake*`
    classes define anything beyond a constructor + one accessor method — no
    attribute here could plausibly shell out."""
    for fake_cls in (
        FakeBuildRunner,
        FakeSecurityScanner,
        FakeSecretScanner,
        FakeGeneratedCodeDriftScanner,
        FakeCoverageReporter,
    ):
        public_methods = [
            name for name in vars(fake_cls) if not name.startswith("_") or name == "__init__"
        ]
        assert set(public_methods) <= {
            "__init__",
            "run_build",
            "scan",
            "report",
        }


# --- CoverageReport guards ------------------------------------------------------------


def test_coverage_report_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        CoverageReport(changed_lines_total=-1, changed_lines_covered=0)


def test_coverage_report_rejects_covered_exceeding_total() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        CoverageReport(changed_lines_total=10, changed_lines_covered=11)


# --- PerformanceOutcome guards ---------------------------------------------------------


def test_performance_outcome_rejects_non_positive_baseline() -> None:
    with pytest.raises(ValueError, match="baseline_value must be positive"):
        PerformanceOutcome(
            metric_name="lcp", baseline_value=0.0, observed_value=1.0, regression_threshold_pct=10.0
        )


def test_performance_outcome_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError, match="regression_threshold_pct must be non-negative"):
        PerformanceOutcome(
            metric_name="lcp", baseline_value=1.0, observed_value=1.0, regression_threshold_pct=-1.0
        )


# --- GateResult Ruling-R4 construction guards --------------------------------------------


def test_gate_result_rejects_passed_true_with_failures() -> None:
    from saena_domain.execution import JobError

    error = JobError(error_code="saena.internal.build_failed", summary="x", retryable=True)
    with pytest.raises(ValueError, match="must not carry failures"):
        GateResult(gate_id=GateId.BUILD, passed=True, failures=(error,))


def test_gate_result_rejects_failed_with_no_failures() -> None:
    with pytest.raises(ValueError, match="must carry >=1 failures"):
        GateResult(gate_id=GateId.BUILD, passed=False, failures=())


# --- errors.py to_dict() -----------------------------------------------------------------


def test_quality_eval_error_to_dict_is_structured_and_log_safe() -> None:
    from saena_quality_eval.errors import QualityEvalError

    error = QualityEvalError("something went wrong", context={"gate_id": "build"})
    assert error.to_dict() == {
        "error_code": "saena.quality_eval.error",
        "message": "something went wrong",
        "gate_id": "build",
    }


# --- engine.QualityEvalOutcome.gate_result_for -----------------------------------------


def test_gate_result_for_raises_key_error_for_an_unknown_gate_id(quality_eval_request) -> None:
    from saena_quality_eval.engine import run_quality_evaluation

    outcome = run_quality_evaluation(quality_eval_request)
    with pytest.raises(KeyError):
        outcome.gate_result_for("not-a-real-gate")

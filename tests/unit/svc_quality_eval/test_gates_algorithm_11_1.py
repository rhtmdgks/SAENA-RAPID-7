"""Pure gate function tests for the 10 Algorithm §11.1 mandatory gates —
happy path + failure path for each, including the explicit negative-test
list item "unsupported-claim content-fidelity FAIL"."""

from __future__ import annotations

from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gates import (
    gate_accessibility,
    gate_build,
    gate_content_fidelity,
    gate_crawlability,
    gate_diff_rationality,
    gate_link_route,
    gate_performance,
    gate_security,
    gate_structured_data,
    gate_tests,
)
from saena_quality_eval.inputs import (
    AccessibilityOutcome,
    BuildOutcome,
    Claim,
    ContentFidelityOutcome,
    CrawlabilityOutcome,
    DiffHunk,
    LinkRouteOutcome,
    PatchDiff,
    PerformanceOutcome,
    SecurityScanOutcome,
    StructuredDataOutcome,
    TestOutcome,
)


def test_build_gate_passes_on_zero_exit() -> None:
    result = gate_build(BuildOutcome(succeeded=True, command="make build", exit_code=0))
    assert result.passed is True
    assert result.gate_id == GateId.BUILD
    assert result.failures == ()


def test_build_gate_fails_on_nonzero_exit() -> None:
    result = gate_build(BuildOutcome(succeeded=False, command="make build", exit_code=1))
    assert result.passed is False
    assert len(result.failures) == 1
    assert result.failures[0].error_code == "saena.internal.build_failed"


def test_tests_gate_passes_when_all_pass() -> None:
    outcome = TestOutcome(suite="unit+integration", total=15, passed=15, failed=0)
    assert gate_tests(outcome).passed is True


def test_tests_gate_fails_when_any_fail() -> None:
    outcome = TestOutcome(suite="unit", total=10, passed=9, failed=1, failing_test_names=("t1",))
    result = gate_tests(outcome)
    assert result.passed is False
    assert "t1" in result.failures[0].redacted_detail["failing_tests"]


def test_link_route_gate_passes_with_no_errors() -> None:
    assert gate_link_route(LinkRouteOutcome()).passed is True


def test_link_route_gate_fails_on_broken_link() -> None:
    result = gate_link_route(LinkRouteOutcome(broken_links=("/missing",)))
    assert result.passed is False


def test_crawlability_gate_passes_when_clean() -> None:
    assert gate_crawlability(CrawlabilityOutcome()).passed is True


def test_crawlability_gate_fails_when_paths_blocked() -> None:
    result = gate_crawlability(CrawlabilityOutcome(blocked_paths=("/blog",)))
    assert result.passed is False


def test_crawlability_gate_fails_when_rendering_not_ok() -> None:
    result = gate_crawlability(CrawlabilityOutcome(rendering_ok=False))
    assert result.passed is False


def test_structured_data_gate_passes_when_clean() -> None:
    assert gate_structured_data(StructuredDataOutcome()).passed is True


def test_structured_data_gate_fails_on_fabricated_markup() -> None:
    result = gate_structured_data(StructuredDataOutcome(fabricated_markup_paths=("/product/1",)))
    assert result.passed is False


def test_content_fidelity_gate_passes_when_every_claim_has_evidence() -> None:
    outcome = ContentFidelityOutcome(claims=(Claim("C-01", "EV-01"), Claim("C-02", "EV-02")))
    assert gate_content_fidelity(outcome).passed is True


def test_content_fidelity_gate_fails_on_a_single_unsupported_claim() -> None:
    """Explicit negative/edge test: unsupported-claim content-fidelity FAIL
    (zero tolerance — Algorithm §11.1)."""
    outcome = ContentFidelityOutcome(claims=(Claim("C-01", "EV-01"), Claim("C-02", None)))
    result = gate_content_fidelity(outcome)
    assert result.passed is False
    assert result.gate_id == GateId.CONTENT_FIDELITY
    assert len(result.failures) == 1
    assert result.failures[0].error_code == "saena.validation.unsupported_claim"
    assert result.failures[0].redacted_detail["claim_id"] == "C-02"


def test_content_fidelity_gate_reports_every_unsupported_claim_independently() -> None:
    outcome = ContentFidelityOutcome(claims=(Claim("C-01", None), Claim("C-02", None)))
    result = gate_content_fidelity(outcome)
    assert result.passed is False
    assert len(result.failures) == 2


def test_security_gate_passes_with_zero_findings() -> None:
    assert gate_security(SecurityScanOutcome()).passed is True


def test_security_gate_fails_on_any_secret_leak() -> None:
    result = gate_security(SecurityScanOutcome(secret_leak_count=1))
    assert result.passed is False


def test_security_gate_fails_on_any_injection_finding() -> None:
    result = gate_security(SecurityScanOutcome(injection_finding_count=1))
    assert result.passed is False


def test_security_gate_fails_on_any_supply_chain_anomaly() -> None:
    result = gate_security(SecurityScanOutcome(supply_chain_anomaly_count=1))
    assert result.passed is False


def test_accessibility_gate_passes_with_no_critical_violations() -> None:
    assert gate_accessibility(AccessibilityOutcome()).passed is True


def test_accessibility_gate_fails_on_critical_violation() -> None:
    result = gate_accessibility(AccessibilityOutcome(critical_violations=("missing-alt-text",)))
    assert result.passed is False


def test_performance_gate_passes_within_threshold() -> None:
    outcome = PerformanceOutcome(
        metric_name="lcp", baseline_value=2.0, observed_value=2.1, regression_threshold_pct=10.0
    )
    assert gate_performance(outcome).passed is True


def test_performance_gate_passes_on_improvement() -> None:
    outcome = PerformanceOutcome(
        metric_name="lcp", baseline_value=2.0, observed_value=1.5, regression_threshold_pct=10.0
    )
    assert gate_performance(outcome).passed is True


def test_performance_gate_fails_beyond_threshold() -> None:
    outcome = PerformanceOutcome(
        metric_name="lcp", baseline_value=2.0, observed_value=2.5, regression_threshold_pct=10.0
    )
    result = gate_performance(outcome)
    assert result.passed is False


def test_diff_rationality_gate_passes_when_every_hunk_is_linked() -> None:
    diff = PatchDiff(
        changed_files=("a.py",),
        hunks=(DiffHunk(file_path="a.py", hunk_id="h1", patch_unit_id="PU-01"),),
    )
    result = gate_diff_rationality(diff, approved_patch_unit_ids=frozenset({"PU-01"}))
    assert result.passed is True


def test_diff_rationality_gate_fails_on_unlinked_hunk() -> None:
    diff = PatchDiff(
        changed_files=("a.py",),
        hunks=(DiffHunk(file_path="a.py", hunk_id="h1", patch_unit_id=None),),
    )
    result = gate_diff_rationality(diff, approved_patch_unit_ids=frozenset({"PU-01"}))
    assert result.passed is False


def test_diff_rationality_gate_fails_on_hunk_linked_to_unapproved_patch_unit() -> None:
    diff = PatchDiff(
        changed_files=("a.py",),
        hunks=(DiffHunk(file_path="a.py", hunk_id="h1", patch_unit_id="PU-99"),),
    )
    result = gate_diff_rationality(diff, approved_patch_unit_ids=frozenset({"PU-01"}))
    assert result.passed is False

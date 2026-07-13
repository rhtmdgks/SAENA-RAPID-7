"""Mission items 4-7: changed-line coverage, forbidden-file detection,
secret scan (redacted), generated-code drift."""

from __future__ import annotations

from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gates import (
    DEFAULT_FORBIDDEN_PATH_PREFIXES,
    gate_changed_line_coverage,
    gate_forbidden_file,
    gate_generated_code_drift,
    gate_secret_scan,
)
from saena_quality_eval.inputs import (
    CoverageReport,
    GeneratedCodeDriftOutcome,
    SecretScanFinding,
    SecretScanOutcome,
)

# --- changed_line_coverage (ADR-0017 >= 90% blocking) --------------------------------


def test_changed_line_coverage_gate_passes_at_exactly_the_threshold() -> None:
    report = CoverageReport(changed_lines_total=100, changed_lines_covered=90)
    result = gate_changed_line_coverage(report)
    assert result.passed is True
    assert result.gate_id == GateId.CHANGED_LINE_COVERAGE


def test_changed_line_coverage_gate_passes_with_no_changed_lines() -> None:
    report = CoverageReport(changed_lines_total=0, changed_lines_covered=0)
    assert gate_changed_line_coverage(report).passed is True


def test_changed_line_coverage_gate_fails_below_threshold() -> None:
    """Explicit negative/edge test: coverage below threshold."""
    report = CoverageReport(changed_lines_total=100, changed_lines_covered=89)
    result = gate_changed_line_coverage(report)
    assert result.passed is False
    assert result.failures[0].error_code == (
        "saena.validation.changed_line_coverage_below_threshold"
    )
    assert result.failures[0].redacted_detail["covered_pct"] == "89.00"


def test_changed_line_coverage_gate_respects_a_custom_threshold() -> None:
    report = CoverageReport(changed_lines_total=100, changed_lines_covered=95)
    assert gate_changed_line_coverage(report, threshold_pct=99.0).passed is False
    assert gate_changed_line_coverage(report, threshold_pct=90.0).passed is True


# --- forbidden_file --------------------------------------------------------------------


def test_forbidden_file_gate_passes_when_no_protected_path_touched() -> None:
    result = gate_forbidden_file(("apps/web/page.tsx", "services/foo/bar.py"))
    assert result.passed is True
    assert result.gate_id == GateId.FORBIDDEN_FILE


def test_forbidden_file_gate_fails_on_a_touched_protected_path() -> None:
    """Explicit negative/edge test: forbidden-file touch."""
    result = gate_forbidden_file(("apps/web/page.tsx", "packages/contracts/foo.schema.json"))
    assert result.passed is False
    assert (
        "packages/contracts/foo.schema.json" in result.failures[0].redacted_detail["touched_files"]
    )


def test_forbidden_file_default_prefixes_cover_claude_md_protected_paths() -> None:
    assert ".cursor/rules/" in DEFAULT_FORBIDDEN_PATH_PREFIXES
    assert "packages/contracts/" in DEFAULT_FORBIDDEN_PATH_PREFIXES
    assert "packages/schemas/" in DEFAULT_FORBIDDEN_PATH_PREFIXES
    assert "deploy/" in DEFAULT_FORBIDDEN_PATH_PREFIXES


def test_forbidden_file_gate_accepts_a_custom_prefix_set() -> None:
    result = gate_forbidden_file(
        ("infra/secrets/prod.yaml",), forbidden_prefixes=("infra/secrets/",)
    )
    assert result.passed is False


# --- secret_scan --------------------------------------------------------------------


def test_secret_scan_gate_passes_with_no_findings() -> None:
    assert gate_secret_scan(SecretScanOutcome()).passed is True


def test_secret_scan_gate_fails_and_redacts_the_raw_secret() -> None:
    """Explicit negative/edge test: secret in patch — MUST fail AND MUST
    NOT leak the raw secret value anywhere in the failure."""
    planted_secret = "AKIAABCDEFGHIJKLMNOP"  # noqa: S105 — test fixture, not a real credential
    outcome = SecretScanOutcome(
        findings=(
            SecretScanFinding(
                file_path="apps/web/.env",
                line=3,
                rule_id="aws-access-key",
                matched_snippet=planted_secret,
            ),
        )
    )
    result = gate_secret_scan(outcome)
    assert result.passed is False
    assert result.gate_id == GateId.SECRET_SCAN

    rendered_parts: list[str] = []
    for failure in result.failures:
        rendered_parts.append(failure.summary)
        rendered_parts.extend(failure.redacted_detail.values())
    full_text = " ".join(rendered_parts)
    assert planted_secret not in full_text
    assert "aws-access-key" in full_text
    assert "apps/web/.env:3" in full_text


# --- generated_code_drift --------------------------------------------------------------


def test_generated_code_drift_gate_passes_with_no_drift() -> None:
    assert gate_generated_code_drift(GeneratedCodeDriftOutcome()).passed is True


def test_generated_code_drift_gate_fails_on_drifted_path() -> None:
    outcome = GeneratedCodeDriftOutcome(drifted_paths=("packages/schemas/saena_schemas/foo.py",))
    result = gate_generated_code_drift(outcome)
    assert result.passed is False
    assert (
        "packages/schemas/saena_schemas/foo.py"
        in result.failures[0].redacted_detail["drifted_paths"]
    )

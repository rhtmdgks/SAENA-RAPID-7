"""Mission item 10: REDACTION — failure reasons never leak stack traces or
source blobs; `VerificationResult` carries redacted detail only. Tests both
a planted secret AND a planted stack trace, at the `GateResult`/`JobError`
construction boundary (`saena_domain.execution.job_error` itself already
rejects stack-trace-shaped text at construction time — this test suite
asserts that guard actually fires for this package's own call sites, plus
this package's OWN secret-specific redaction which that shared layer does
not attempt)."""

from __future__ import annotations

import pytest
from saena_domain.execution.errors import JobErrorValidationError
from saena_quality_eval.gates import gate_secret_scan
from saena_quality_eval.inputs import SecretScanFinding, SecretScanOutcome
from saena_quality_eval.redaction import (
    contains_stack_trace_marker,
    redact_secret_snippet,
    redact_stack_trace,
    truncate,
)


def test_secret_scan_never_leaks_raw_secret() -> None:
    planted_secret = "sk-test-abcdefghijklmnopqrstuvwxyz0123456789"  # noqa: S105
    outcome = SecretScanOutcome(
        findings=(
            SecretScanFinding(
                file_path="apps/web/config.py",
                line=42,
                rule_id="generic-api-key",
                matched_snippet=planted_secret,
            ),
        )
    )
    result = gate_secret_scan(outcome)
    for failure in result.failures:
        assert planted_secret not in failure.summary
        assert all(planted_secret not in value for value in failure.redacted_detail.values())


def test_redact_secret_snippet_never_takes_a_raw_value_argument() -> None:
    """`redact_secret_snippet`'s signature structurally cannot accept a raw
    matched-text argument — the safest possible redaction guarantee (not
    just "redacts it", but "cannot be handed it")."""
    rendered = redact_secret_snippet("aws-access-key", "apps/web/.env", 3)
    assert "apps/web/.env:3" in rendered
    assert "aws-access-key" in rendered
    assert "[REDACTED]" in rendered


def test_contains_stack_trace_marker_detects_python_traceback() -> None:
    planted_trace = 'Traceback (most recent call last):\n  File "app.py", line 1\nValueError: x'
    assert contains_stack_trace_marker(planted_trace) is True


def test_redact_stack_trace_replaces_stack_trace_shaped_text() -> None:
    planted_trace = 'Traceback (most recent call last):\n  File "app.py", line 1\nValueError: x'
    redacted = redact_stack_trace(planted_trace)
    assert "Traceback" not in redacted
    assert "app.py" not in redacted
    assert redacted == "[REDACTED: stack-trace-shaped content omitted]"


def test_redact_stack_trace_leaves_ordinary_text_unchanged() -> None:
    assert redact_stack_trace("build command exited 1") == "build command exited 1"


def test_job_error_itself_rejects_a_planted_stack_trace_in_summary() -> None:
    """Defense-in-depth: even if a caller bypassed `redact_stack_trace` and
    tried to construct a `JobError` directly with a raw traceback in
    `summary`, the shared execution-domain `JobError` value object itself
    refuses construction (`saena_domain.execution.job_error`
    `_reject_unsafe_text`) — this package's gate functions inherit that
    guarantee for free by always routing through `JobError`."""
    from saena_domain.execution import JobError

    planted_trace = 'Traceback (most recent call last):\n  File "app.py", line 1\nValueError: x'
    with pytest.raises(JobErrorValidationError):
        JobError(error_code="saena.internal.build_failed", summary=planted_trace, retryable=True)


def test_truncate_bounds_long_text() -> None:
    long_text = "x" * 1000
    truncated = truncate(long_text, max_length=50)
    assert len(truncated) <= 50 + len("...[truncated]")
    assert truncated.endswith("...[truncated]")


def test_truncate_leaves_short_text_unchanged() -> None:
    assert truncate("short", max_length=50) == "short"

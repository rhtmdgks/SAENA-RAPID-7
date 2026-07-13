"""JobError — canonical error model shape, wire-payload/contract conformance,
and redaction (never a stack trace / oversized blob, never leaks
redacted_detail into the serialized wire payload)."""

from __future__ import annotations

import pytest
from _schema_support import ERROR_DETAIL_SCHEMA_PATH, schema_errors
from saena_domain.execution.errors import JobErrorValidationError
from saena_domain.execution.job_error import KNOWN_ERROR_CATEGORIES, JobError


def test_valid_job_error_constructs_and_exposes_fields() -> None:
    err = JobError(
        error_code="saena.upstream_engine.timeout",
        summary="engine call timed out after 30s",
        retryable=True,
    )
    assert err.error_code == "saena.upstream_engine.timeout"
    assert err.retryable is True
    assert err.redacted_detail == {}


def test_job_error_is_frozen() -> None:
    err = JobError(error_code="saena.internal.unexpected", summary="x", retryable=False)
    with pytest.raises(AttributeError):
        err.summary = "y"  # type: ignore[misc]


def test_to_error_detail_payload_matches_error_detail_contract_exactly() -> None:
    err = JobError(
        error_code="saena.validation.schema_mismatch",
        summary="payload violates the bound contract",
        retryable=False,
        redacted_detail={"gate_id": "lint"},
    )
    payload = err.to_error_detail_payload()
    assert payload == {
        "error_code": "saena.validation.schema_mismatch",
        "retryable": False,
        "summary": "payload violates the bound contract",
    }
    assert schema_errors(ERROR_DETAIL_SCHEMA_PATH, payload) == []


def test_to_error_detail_payload_never_includes_redacted_detail() -> None:
    """Redaction guarantee: even a non-empty, VALID redacted_detail never
    reaches the wire payload — common/error-detail/v1 is closed
    (additionalProperties: false, exactly 3 fields) and ADR-0015's audit
    scope is error_code + trace_id only."""
    err = JobError(
        error_code="saena.internal.unexpected",
        summary="build step failed",
        retryable=False,
        redacted_detail={"exit_code": "1", "step": "compile"},
    )
    payload = err.to_error_detail_payload()
    assert "redacted_detail" not in payload
    assert "exit_code" not in payload
    assert set(payload.keys()) == {"error_code", "retryable", "summary"}


@pytest.mark.parametrize(
    "bad_error_code",
    [
        "",
        "not-namespaced",
        "saena.onlyonepart",
        "saena.UPPER.case",
        "saena.validation",  # missing reason segment
        "wrong_prefix.validation.schema_mismatch",
    ],
)
def test_malformed_error_code_rejected(bad_error_code: str) -> None:
    with pytest.raises(JobErrorValidationError):
        JobError(error_code=bad_error_code, summary="x", retryable=False)


def test_error_code_outside_adr_0015_taxonomy_rejected() -> None:
    with pytest.raises(JobErrorValidationError):
        JobError(error_code="saena.made_up_category.oops", summary="x", retryable=False)


@pytest.mark.parametrize("category", sorted(KNOWN_ERROR_CATEGORIES))
def test_every_adr_0015_category_accepted(category: str) -> None:
    JobError(error_code=f"saena.{category}.some_reason", summary="ok", retryable=False)


def test_empty_summary_rejected() -> None:
    with pytest.raises(JobErrorValidationError):
        JobError(error_code="saena.internal.unexpected", summary="", retryable=False)


def test_oversized_summary_rejected() -> None:
    with pytest.raises(JobErrorValidationError):
        JobError(error_code="saena.internal.unexpected", summary="x" * 501, retryable=False)


def test_max_length_summary_accepted() -> None:
    JobError(error_code="saena.internal.unexpected", summary="x" * 500, retryable=False)


def test_stack_trace_shaped_summary_rejected() -> None:
    summary = 'Traceback (most recent call last):\n  File "app.py", line 1, in <module>'
    with pytest.raises(JobErrorValidationError):
        JobError(error_code="saena.internal.unexpected", summary=summary, retryable=False)


def test_stack_trace_shaped_redacted_detail_value_rejected() -> None:
    with pytest.raises(JobErrorValidationError):
        JobError(
            error_code="saena.internal.unexpected",
            summary="build failed",
            retryable=False,
            redacted_detail={"trace": 'Traceback (most recent call last):\n  File "x.py"'},
        )


def test_oversized_redacted_detail_value_rejected() -> None:
    with pytest.raises(JobErrorValidationError):
        JobError(
            error_code="saena.internal.unexpected",
            summary="build failed",
            retryable=False,
            redacted_detail={"blob": "x" * 501},
        )


def test_too_many_redacted_detail_entries_rejected() -> None:
    detail = {f"k{i}": "v" for i in range(17)}
    with pytest.raises(JobErrorValidationError):
        JobError(
            error_code="saena.internal.unexpected",
            summary="build failed",
            retryable=False,
            redacted_detail=detail,
        )


def test_max_entries_redacted_detail_accepted() -> None:
    detail = {f"k{i}": "v" for i in range(16)}
    JobError(
        error_code="saena.internal.unexpected",
        summary="build failed",
        retryable=False,
        redacted_detail=detail,
    )

"""`verification.build_verification_result` — mission item 2 ("Aggregate
into a VerificationResult (validate against the verification-result
contract / codegen model)"), Ruling R4 bidirectional failures rule."""

from __future__ import annotations

import pytest
from saena_domain.execution import JobError
from saena_quality_eval.errors import VerificationResultValidationError
from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gate_result import failed, passed
from saena_quality_eval.verification import build_verification_result

_COMMON_KWARGS = dict(
    tenant_id="acme-co",
    run_id="run-0001",
    patch_unit_id="PU-01",
    worktree_commit="abc1234",
    evaluated_at="2026-07-13T00:00:00Z",
)


def test_passed_gate_result_omits_the_failures_key() -> None:
    payload = build_verification_result(gate_result=passed(GateId.BUILD), **_COMMON_KWARGS)
    assert payload["status"] == "passed"
    assert "failures" not in payload
    assert payload["gate_id"] == "build"


def test_failed_gate_result_carries_at_least_one_failure() -> None:
    error = JobError(
        error_code="saena.internal.build_failed", summary="build failed", retryable=True
    )
    payload = build_verification_result(
        gate_result=failed(GateId.BUILD, (error,)), **_COMMON_KWARGS
    )
    assert payload["status"] == "failed"
    assert payload["failures"] == [
        {"error_code": "saena.internal.build_failed", "retryable": True, "summary": "build failed"}
    ]


def test_report_uri_is_included_when_supplied() -> None:
    payload = build_verification_result(
        gate_result=passed(GateId.BUILD), report_uri="artifact://reports/PU-01", **_COMMON_KWARGS
    )
    assert payload["report_uri"] == "artifact://reports/PU-01"


def test_report_uri_omitted_when_not_supplied() -> None:
    payload = build_verification_result(gate_result=passed(GateId.BUILD), **_COMMON_KWARGS)
    assert "report_uri" not in payload


def test_worktree_commit_must_match_the_contract_pattern() -> None:
    """`worktree_commit` must be 7-40 lowercase hex — a non-hex value must
    be rejected before it reaches the wire (contract, not this package's own
    invention)."""
    kwargs = dict(_COMMON_KWARGS)
    kwargs["worktree_commit"] = "not-hex!!"
    with pytest.raises(VerificationResultValidationError):
        build_verification_result(gate_result=passed(GateId.BUILD), **kwargs)


def test_gate_id_is_rendered_as_a_plain_string() -> None:
    payload = build_verification_result(gate_result=passed(GateId.SECRET_SCAN), **_COMMON_KWARGS)
    assert payload["gate_id"] == "secret_scan"
    assert isinstance(payload["gate_id"], str)

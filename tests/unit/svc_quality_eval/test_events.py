"""Mission item 9: emit `quality.gate.passed.v1` / `quality.gate.failed.v1`
via the shared `saena_domain.execution` builders; audit per gate."""

from __future__ import annotations

from saena_domain.execution import JobError
from saena_quality_eval.audit import build_gate_audit_record
from saena_quality_eval.events import (
    QUALITY_GATE_FAILED_EVENT_TYPE,
    QUALITY_GATE_PASSED_EVENT_TYPE,
    build_gate_event_payload,
)
from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gate_result import failed, passed


def test_passed_gate_emits_the_passed_event_without_a_failures_key() -> None:
    event_type, payload = build_gate_event_payload(passed(GateId.BUILD), patch_unit_id="PU-01")
    assert event_type == QUALITY_GATE_PASSED_EVENT_TYPE
    assert payload["gate_id"] == "build"
    assert payload["patch_unit_id"] == "PU-01"
    assert "failures" not in payload


def test_failed_gate_emits_the_failed_event_with_failures() -> None:
    error = JobError(
        error_code="saena.internal.build_failed", summary="build failed", retryable=True
    )
    event_type, payload = build_gate_event_payload(
        failed(GateId.BUILD, (error,)), patch_unit_id="PU-01"
    )
    assert event_type == QUALITY_GATE_FAILED_EVENT_TYPE
    assert payload["failures"] == [
        {"error_code": "saena.internal.build_failed", "retryable": True, "summary": "build failed"}
    ]


def test_report_uri_flows_through_to_the_event_payload() -> None:
    _event_type, payload = build_gate_event_payload(
        passed(GateId.BUILD), patch_unit_id="PU-01", report_uri="artifact://reports/PU-01"
    )
    assert payload["report_uri"] == "artifact://reports/PU-01"


def test_audit_record_is_built_per_gate_and_is_log_safe() -> None:
    error = JobError(
        error_code="saena.internal.secret_detected", summary="1 secret(s) detected", retryable=False
    )
    record = build_gate_audit_record(
        failed(GateId.SECRET_SCAN, (error,)), evaluated_at="2026-07-13T00:00:00Z"
    )
    assert record.gate_id == GateId.SECRET_SCAN
    assert record.status == "failed"
    assert record.error_codes == ("saena.internal.secret_detected",)
    as_dict = record.to_dict()
    assert as_dict["gate_id"] == "secret_scan"
    assert as_dict["error_codes"] == ["saena.internal.secret_detected"]


def test_audit_record_for_a_passing_gate_has_no_error_codes() -> None:
    record = build_gate_audit_record(passed(GateId.BUILD), evaluated_at="2026-07-13T00:00:00Z")
    assert record.status == "passed"
    assert record.error_codes == ()

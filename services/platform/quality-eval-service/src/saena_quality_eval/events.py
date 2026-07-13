"""`build_gate_event_payload` — mission item 9, "emit quality.gate.passed.v1
/ quality.gate.failed.v1 via the builders".

Thin wrapper over `saena_domain.execution.build_quality_gate_passed_payload`
/ `build_quality_gate_failed_payload` (the shared execution-domain layer's
own builders, already validated against
`saena_schemas.event.quality_gate_result_v1.QualityGatePassedFailedV1Payload`
and already enforcing the AsyncAPI channel-layer R4 split — `passed.v1`
never carries `failures`, `failed.v1` always carries >=1). This package adds
NO second builder/validation path; it only selects which of the two
existing builders to call based on `GateResult.passed`, and threads
`GateResult.failures` (already-redacted `JobError`s) through unchanged.
"""

from __future__ import annotations

from typing import Any

from saena_domain.execution import (
    build_quality_gate_failed_payload,
    build_quality_gate_passed_payload,
)

from saena_quality_eval.gate_result import GateResult

QUALITY_GATE_PASSED_EVENT_TYPE = "quality.gate.passed.v1"
QUALITY_GATE_FAILED_EVENT_TYPE = "quality.gate.failed.v1"


def build_gate_event_payload(
    gate_result: GateResult,
    *,
    patch_unit_id: str,
    report_uri: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return `(event_type, payload)` for `gate_result` — `event_type` is
    `quality.gate.passed.v1` iff `gate_result.passed`, else
    `quality.gate.failed.v1`."""
    if gate_result.passed:
        payload = build_quality_gate_passed_payload(
            patch_unit_id=patch_unit_id,
            gate_id=str(gate_result.gate_id),
            report_uri=report_uri,
        )
        return QUALITY_GATE_PASSED_EVENT_TYPE, payload
    payload = build_quality_gate_failed_payload(
        patch_unit_id=patch_unit_id,
        gate_id=str(gate_result.gate_id),
        failures=list(gate_result.failures),
        report_uri=report_uri,
    )
    return QUALITY_GATE_FAILED_EVENT_TYPE, payload


__all__ = [
    "QUALITY_GATE_FAILED_EVENT_TYPE",
    "QUALITY_GATE_PASSED_EVENT_TYPE",
    "build_gate_event_payload",
]

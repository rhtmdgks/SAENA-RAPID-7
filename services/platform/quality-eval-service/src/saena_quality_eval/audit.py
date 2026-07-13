"""Per-gate audit record — mission item 9, "audit per gate".

`GateAuditRecord` is this package's own lightweight, log-safe summary of one
`GateResult` — NOT a full `saena_domain.audit.AuditEntry` hash-chain entry
(that chain is audit-ledger-service's own append-only store, a separate
service this package does not write to directly; a caller wiring a real
quality-eval Job appends one `AuditEntry` per `GateAuditRecord` produced
here via that service's own client/port, out of this package's scope). This
module only fixes what a per-gate audit record CONTAINS: `error_code`s only
(never a raw summary/detail blob) mirrors ADR-0015 "AuditEvent 에러 기록
범위: error_code + trace_id만" applied at gate granularity.
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gate_result import GateResult


@dataclass(frozen=True, slots=True)
class GateAuditRecord:
    """Log-safe, deterministic per-gate audit summary."""

    gate_id: GateId
    status: str
    evaluated_at: str
    error_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "gate_id": str(self.gate_id),
            "status": self.status,
            "evaluated_at": self.evaluated_at,
            "error_codes": list(self.error_codes),
        }


def build_gate_audit_record(gate_result: GateResult, *, evaluated_at: str) -> GateAuditRecord:
    return GateAuditRecord(
        gate_id=gate_result.gate_id,
        status="passed" if gate_result.passed else "failed",
        evaluated_at=evaluated_at,
        error_codes=tuple(f.error_code for f in gate_result.failures),
    )


__all__ = ["GateAuditRecord", "build_gate_audit_record"]

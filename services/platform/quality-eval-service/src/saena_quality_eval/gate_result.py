"""`GateResult` — the pure output of a single gate function.

Mirrors `domain/verification-result/v1`'s own bidirectional failures rule
(Ruling R4: `status=failed` MUST carry >=1 `failures`; `status=passed` MUST
NOT carry a `failures` key at all) at the Python value-object layer, one
step before `verification.build_verification_result` renders it into the
wire shape — `__post_init__` enforces the SAME bidirectional rule here, so a
gate function cannot accidentally construct a `GateResult(passed=True,
failures=(some_error,))` or a `GateResult(passed=False, failures=())` in the
first place.

`failures` holds `saena_domain.execution.JobError` values — the SAME
canonical structured-error type the shared execution-domain layer already
defines (ADR-0015 taxonomy, `to_error_detail_payload()` matching
`common/error-detail/v1` exactly), reused here rather than a second
package-local error-detail DTO.
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_domain.execution import JobError

from saena_quality_eval.gate_ids import GateId


@dataclass(frozen=True, slots=True)
class GateResult:
    """Pure result of evaluating one gate against its (already-collected,
    deterministic) input."""

    gate_id: GateId
    passed: bool
    failures: tuple[JobError, ...] = ()

    def __post_init__(self) -> None:
        if self.passed and self.failures:
            raise ValueError(
                f"GateResult({self.gate_id!r}, passed=True) must not carry failures "
                "(domain/verification-result/v1 Ruling R4)"
            )
        if not self.passed and not self.failures:
            raise ValueError(
                f"GateResult({self.gate_id!r}, passed=False) must carry >=1 failures "
                "(domain/verification-result/v1 Ruling R4)"
            )


def passed(gate_id: GateId) -> GateResult:
    """Convenience constructor for a passing gate (no failures)."""
    return GateResult(gate_id=gate_id, passed=True, failures=())


def failed(gate_id: GateId, failures: tuple[JobError, ...]) -> GateResult:
    """Convenience constructor for a failing gate (`failures` must be
    non-empty — enforced by `GateResult.__post_init__`)."""
    return GateResult(gate_id=gate_id, passed=False, failures=failures)


__all__ = ["GateResult", "failed", "passed"]

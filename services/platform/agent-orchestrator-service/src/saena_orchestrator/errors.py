"""saena_orchestrator error taxonomy."""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base class for all saena_orchestrator errors."""


class SignalRefusedError(OrchestratorError):
    """Raised (internally, non-fatal-to-workflow) when an approval signal
    fails defense-in-depth re-validation (ADR-0003 step 4): contract_hash or
    PlanSnapshot mismatch, or the underlying saena_domain.policy transition
    itself refuses. The workflow catches this and stays in WAITING_APPROVAL
    rather than propagating a workflow failure — a forged/gate-denied signal
    is an expected, auditable event, not a bug.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"approval signal refused: {reason}")


__all__ = ["OrchestratorError", "SignalRefusedError"]

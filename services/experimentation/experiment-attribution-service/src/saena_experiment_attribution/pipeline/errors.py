"""Pipeline-level exceptions (w5-13).

Follows the `saena.<category>.<reason>` `error_code` + structured `context`
shape used throughout `saena_domain` (ADR-0015). The pipeline raises ONLY for
programmer-error / contract-violation conditions that are not a legitimate
measurement outcome (e.g. calling `run_measurement` with ports that disagree
about tenant, or a store that raises an error class this module cannot
interpret). Every FAIL-CLOSED measurement condition (missing GRS policy,
binding reject, incomplete window, insufficient DiD, non-PASS B-gate) is
represented as an honest `ExperimentOutcome` record, never as an exception —
the pipeline's contract is "always produce a record", not "raise on trouble".
"""

from __future__ import annotations

from typing import Any


class PipelineError(Exception):
    """Base class for `saena_experiment_attribution.pipeline` errors.

    Raised only for conditions that are not a legitimate measurement outcome
    (e.g. a persistence-layer error the pipeline cannot honestly interpret as
    any `OutcomeStatus`). Never raised for a fail-closed measurement verdict —
    those are always returned as an `ExperimentOutcome` record instead.
    """

    error_code: str = "saena.experiment_attribution.pipeline.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), **self.context}


__all__ = ["PipelineError"]

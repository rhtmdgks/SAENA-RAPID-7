"""Measurement pipeline orchestration (w5-13).

Composes the Wave-5 `saena_domain.measurement` domain modules, IN ORDER,
fail-closed at every step, into one pure function: `run_measurement`.

    registration + confirmation + observations
        -> GRS eligibility (first, honest — never blocks the outcome record)
        -> binding (registration integrity / contamination)
        -> window check (deployment-confirmed clock, completeness)
        -> DiD per signal
        -> B-gate verdict
        -> evidence bundle seal
        -> ExperimentOutcome record (stored atomically, idempotent replay)

See `orchestrator.py` for the full docstring and `docs/architecture/
wave5-plan.md` (w5-13, E-matrix, Algorithm §7.3 7-day sequence) for the
authoritative design basis. This subpackage is PURE ORCHESTRATION: it
performs no I/O of its own beyond the injected `MeasurementPorts`, and
contains no measurement/statistics/verdict logic that does not already live
in `saena_domain.measurement.*` — this module only calls those functions in
the right order and assembles their outputs.
"""

from __future__ import annotations

from .errors import PipelineError
from .inputs import (
    MeasurementInputs,
    MeasurementPolicies,
    MeasurementPorts,
)
from .orchestrator import run_measurement
from .outcome import ExperimentOutcome, OutcomeStatus

__all__ = [
    "ExperimentOutcome",
    "MeasurementInputs",
    "MeasurementPolicies",
    "MeasurementPorts",
    "OutcomeStatus",
    "PipelineError",
    "run_measurement",
]

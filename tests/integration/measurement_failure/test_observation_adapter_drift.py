"""Observation adapter drift (w5-20 deliverable 2, bullet 5): a drifted
observation adapter -> UNDETERMINED(observation_adapter_drift), never silent.

"Drift" here means an upstream observation producer emitting a signal whose
`layer` value falls OUTSIDE the closed `OutcomeLayer` vocabulary (Algorithm
§3.5:159's five-member closed set) — the concrete, reproducible shape of
"the observation adapter drifted from its approved fixture/contract"
(`reason_codes.py`). Two levels:

1. Domain level (`b_gate.decide_b_verdict` cannot even score such a signal —
   `orchestrator._signal_result` maps it to `None` and the b-gate step marks
   `adapter_drift=True` on the `WindowState`), proven directly against the
   real `b_gate` module with a `SignalResult`-construction-time drift (an
   `OutcomeLayer(...)` value that does not exist is refused at construction
   — pydantic/enum fail-closed).
2. Pipeline level: `run_measurement` fed a signal with an out-of-vocabulary
   `layer` (e.g. the explicitly-forbidden `"conversion"` — Algorithm §4:212 /
   k3s §12:553) over REAL Postgres-backed ports resolves UNDETERMINED with
   `ReasonCode.OBSERVATION_ADAPTER_DRIFT`, and the drift is never silently
   dropped from the reason codes even though every OTHER (in-vocabulary)
   signal in the same run still qualifies.
"""

from __future__ import annotations

import dataclasses

import pytest
from measurement_failure_factories import make_pg_ports
from pipeline_factories import make_happy_path_inputs, make_policies
from saena_domain.measurement.outcome_layer import OutcomeLayer
from saena_domain.measurement.reason_codes import ReasonCode
from saena_experiment_attribution.pipeline import OutcomeStatus, run_measurement

pytestmark = pytest.mark.integration


def test_conversion_is_not_a_constructable_outcome_layer() -> None:
    """`conversion` is deliberately excluded from the closed `OutcomeLayer`
    vocabulary (Algorithm §4:212 / k3s §12:553 — forbidden as a 7-day B-layer
    success metric). Constructing it must fail, not silently coerce."""
    with pytest.raises(ValueError):  # noqa: PT011 - enum ValueError, no narrower type exposed
        OutcomeLayer("conversion")


def test_pipeline_out_of_vocabulary_layer_signal_is_undetermined_adapter_drift(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """One drifted signal (layer="conversion", outside the closed vocabulary)
    mixed in with otherwise-qualifying signals over REAL Postgres-backed
    ports: the pipeline must surface OBSERVATION_ADAPTER_DRIFT and resolve
    UNDETERMINED — the drift is never silently absorbed just because other
    signals in the same run looked fine."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    drifted_signal = inputs.signals[0].model_copy(update={"layer": "conversion"})
    drifted_inputs = dataclasses.replace(inputs, signals=(drifted_signal, *inputs.signals[1:]))
    policies = make_policies(registration)
    ports = make_pg_ports(postgres_url)

    outcome = run_measurement(drifted_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.OBSERVATION_ADAPTER_DRIFT in outcome.reason_codes
    # Never silently upgraded to PASS/FAIL despite the remaining signal(s)
    # still being individually qualifying.
    assert outcome.status is not OutcomeStatus.PASS


def test_pipeline_all_signals_drifted_is_undetermined_not_a_crash(
    postgres_url: str,
    engine,
    run,  # noqa: ANN001
) -> None:
    """Total adapter drift (every signal's layer out-of-vocabulary) must
    still resolve to an honest UNDETERMINED outcome record — never an
    unhandled exception escaping the pipeline (fail-closed, not fail-crash)."""
    inputs, registration = make_happy_path_inputs(num_qualifying_layers=2)
    fully_drifted_signals = tuple(
        s.model_copy(update={"layer": "conversion"}) for s in inputs.signals
    )
    drifted_inputs = dataclasses.replace(inputs, signals=fully_drifted_signals)
    policies = make_policies(registration)
    ports = make_pg_ports(postgres_url)

    outcome = run_measurement(drifted_inputs, ports, policies)

    assert outcome.status is OutcomeStatus.UNDETERMINED
    assert ReasonCode.OBSERVATION_ADAPTER_DRIFT in outcome.reason_codes

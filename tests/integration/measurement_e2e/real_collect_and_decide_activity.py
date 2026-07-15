"""A REAL (non-fixture) `collect_and_decide` Temporal activity for the c5-01
container E2E — registers the actual `run_measurement` pipeline (w5-13) behind
the SAME `COLLECT_AND_DECIDE_ACTIVITY` name the workflow (w5-14) calls by
string, so a durable-timer-driven decision in this lane is a REAL composed
pipeline run against REAL Postgres ports, not the workflow unit suite's
`FixtureCollectAndDecide` stand-in.

`saena_experiment_attribution.workflow.activities.CollectAndDecideInput`
carries only `(idempotency_key, content_fingerprint)` — the workflow itself
never handles raw registration/submission/signal data (module docstring:
"this workflow never handles raw observations"). A real production activity
would resolve those from a store keyed by the window's idempotency key; that
lookup infrastructure is out of scope for w5-19/c5-01 (w5-15's observation
adapter concern). This module supplies an HONEST, explicitly test-only
substitute: a plain in-process dict the test seeds BEFORE starting the
workflow (`register_scenario`), keyed by the SAME `idempotency_key` the
`Accepted` signal carries — the activity looks the scenario up by that key and
runs the REAL pipeline. This is not a production data-access pattern; it is
the minimum seam needed to prove the Temporal-driven timer fires the ACTUAL
`run_measurement` composition against ACTUAL Postgres, which is the point of
this lane (task instruction: "the actual ... workflow ... through ... the
actual experiment-attribution boundary + run_measurement pipeline").
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from saena_experiment_attribution.pipeline.inputs import MeasurementInputs, MeasurementPolicies
from saena_experiment_attribution.pipeline.orchestrator import run_measurement
from saena_experiment_attribution.workflow.activities import (
    COLLECT_AND_DECIDE_ACTIVITY,
    CollectAndDecideInput,
    CollectAndDecideResult,
)
from temporalio import activity


@dataclass(frozen=True, slots=True)
class _RegisteredScenario:
    inputs: MeasurementInputs
    policies: MeasurementPolicies


#: Test-only in-process registry: idempotency_key -> (inputs, policies). Reset
#: per test via `clear_registry()` (each Worker/workflow run in this lane uses
#: a fresh idempotency key, but tests still clear defensively between runs).
_REGISTRY: dict[str, _RegisteredScenario] = {}


def register_scenario(
    idempotency_key: str, inputs: MeasurementInputs, policies: MeasurementPolicies
) -> None:
    """Seed the registry the real activity below reads from. Must be called
    BEFORE the workflow's deployment-confirmed signal is delivered (the
    activity runs at timer-fire time, well after registration)."""
    _REGISTRY[idempotency_key] = _RegisteredScenario(inputs=inputs, policies=policies)


def clear_registry() -> None:
    _REGISTRY.clear()


def make_real_collect_and_decide_activity(postgres_url: str):  # noqa: ANN201
    """Build a `@activity.defn(name=COLLECT_AND_DECIDE_ACTIVITY)` closure bound
    to `postgres_url` — registered on the test Worker IN PLACE OF
    `collect_and_decide_fixture_activity`, so `MeasurementWorkflow.run`'s
    by-name activity call reaches this real implementation without any
    workflow-code change (activities.py's own "stub Activity, real impl
    later" discipline)."""
    # Imported lazily so a worktree without the container harness available
    # (pure pipeline-only callers) never needs sync_facade at import time.
    from measurement_e2e_container_harness import make_pg_ports  # noqa: PLC0415

    @activity.defn(name=COLLECT_AND_DECIDE_ACTIVITY)
    async def real_collect_and_decide_activity(
        activity_input: CollectAndDecideInput,
    ) -> CollectAndDecideResult:
        activity.heartbeat(
            "real_collect_and_decide: running run_measurement against Postgres",
            activity_input.idempotency_key,
        )
        registered = _REGISTRY.get(activity_input.idempotency_key)
        if registered is None:
            # Honest failure — never a silently-fabricated outcome_ref for a
            # scenario the test forgot to (or could not) register.
            raise RuntimeError(
                f"no registered scenario for idempotency_key={activity_input.idempotency_key!r} "
                "— register_scenario() must be called before the workflow's "
                "deployment-confirmed signal is delivered"
            )

        def _run_sync() -> str:
            # `run_measurement` is a synchronous function whose Postgres ports
            # are the SYNC FACADES over the real w5-10 asyncpg adapter — each
            # facade call does its own `asyncio.run(...)` (sync_facade.py
            # module docstring: "one fresh event loop per call"). This
            # activity coroutine is ALREADY running inside the Worker's own
            # event loop, so calling `run_measurement` directly here would
            # hit `asyncio.run()`'s "cannot be called from a running event
            # loop" guard. Running it on a dedicated OS thread (via
            # `asyncio.to_thread` below) gives it a thread with NO running
            # loop, exactly like a normal synchronous pytest test body — the
            # SAME sync-facade code path every other scenario in this lane
            # exercises directly, just off the activity's own loop.
            ports = make_pg_ports(postgres_url)
            outcome = run_measurement(registered.inputs, ports, registered.policies)
            return outcome.status.value

        status_value = await asyncio.to_thread(_run_sync)
        return CollectAndDecideResult(outcome_ref=f"outcome-ref:{status_value}")

    return real_collect_and_decide_activity


__all__ = [
    "clear_registry",
    "make_real_collect_and_decide_activity",
    "register_scenario",
]

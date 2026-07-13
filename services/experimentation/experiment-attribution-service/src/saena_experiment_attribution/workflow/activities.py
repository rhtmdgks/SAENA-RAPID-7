"""Temporal Activities for ``MeasurementWorkflow``.

Two activities, both kept OUT of the deterministic workflow body:

1. ``derive_window`` — wraps the domain ``start_measurement_window`` call. Window
   derivation pairs with a ``registration_view`` lookup and is a domain call the
   workflow keeps out of its pure body (wave5-plan.md w5-14: "derive window via
   ``saena_domain.measurement.clock.start_measurement_window`` in an activity —
   domain call with registration_view lookup is nondeterministic-adjacent; keep
   workflow pure, activity returns the frozen window record"). It NEVER
   re-validates trust — it receives an already-``Accepted`` confirmation + the
   trusted ``registration_view`` and returns the frozen window (or the
   ``deployment_late`` verdict) via a serializable result.

2. ``collect_and_decide`` — the STUB interface at the window's timer fire. The
   ACTUAL DiD/B-gate/evidence pipeline is w5-13's (pipeline/**). This unit
   defines only the activity CONTRACT (``CollectAndDecidePort`` Protocol) plus a
   deterministic ``FixtureCollectAndDecide`` implementation for tests. The
   workflow calls the activity by NAME so w5-13's real implementation drops in
   behind this signature without a workflow change (same "stub Activity, real
   impl later" discipline as ``saena_orchestrator.activities.run_execution_activity``).

Reuse discipline: ``derive_window`` calls the domain ``start_measurement_window``
verbatim — it does NOT reimplement the Day-2 rule or the window arithmetic
(wave5-plan.md: REUSE, do not reimplement validation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from saena_domain.measurement.clock import (
    MeasurementPolicy,
    MeasurementWindow,
    Undetermined,
    start_measurement_window,
)
from saena_domain.measurement.confirmation import Accepted
from temporalio import activity

from saena_experiment_attribution.workflow.timeouts import HEARTBEAT_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class FrozenWindowRecord:
    """Serializable projection of a domain ``MeasurementWindow``.

    The domain ``MeasurementWindow`` deliberately guards its ``__init__`` behind
    a private token so no code path can construct a window from a bare
    timestamp — which ALSO means it cannot be deserialized across the Temporal
    payload boundary (the converter would have to call that guarded
    constructor). That is by design: a ``MeasurementWindow`` only ever exists in
    the process where ``start_measurement_window`` created it. What crosses the
    activity boundary is THIS frozen, plain record of the already-derived
    window's facts — the workflow consumes the absolute instants; it never
    (re)derives them.
    """

    anchor: datetime
    end: datetime
    window_days: int
    idempotency_key: str
    content_fingerprint: str

    @classmethod
    def from_domain(cls, window: MeasurementWindow) -> FrozenWindowRecord:
        return cls(
            anchor=window.anchor,
            end=window.end,
            window_days=window.window_days,
            idempotency_key=window.idempotency_key,
            content_fingerprint=window.content_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class DeriveWindowInput:
    """Input to ``derive_window``: the already-``Accepted`` confirmation. Its
    embedded ``registration_view`` is the trusted registration the window is
    anchored against — ``start_measurement_window`` asserts they match, so we
    pass the Accepted (which carries both) rather than a loose pair a caller
    could mismatch.
    """

    accepted: Accepted
    #: Optional policy override; None → domain default (7-day window, Day-2
    #: deadline). Passed through verbatim to ``start_measurement_window``.
    policy: MeasurementPolicy | None = None


@dataclass(frozen=True, slots=True)
class DeriveWindowResult:
    """Serializable result of ``derive_window``.

    Exactly one of ``window`` / ``deployment_late`` is set:
    - ``window`` present → the clock started; carries the ``FrozenWindowRecord``
      projection (anchor/end/window_days/idempotency_key/fingerprint) of the
      domain window ``start_measurement_window`` derived.
    - ``deployment_late`` True → ``start_measurement_window`` returned
      ``Undetermined(deployment_late)``; the workflow completes UNDETERMINED and
      NEVER starts the timer (§7.3:483).
    """

    window: FrozenWindowRecord | None
    deployment_late: bool


@dataclass(frozen=True, slots=True)
class CollectAndDecideInput:
    """Input to the collect-and-decide activity at timer fire.

    Carries the window identity only (the pipeline owns collecting observations
    against ``idempotency_key`` and running DiD/B-gate — this workflow never
    handles raw observations). ``idempotency_key`` binds the decision to the
    exact window this run measured.
    """

    idempotency_key: str
    content_fingerprint: str


@dataclass(frozen=True, slots=True)
class CollectAndDecideResult:
    """Result of collect-and-decide: an opaque outcome record REFERENCE.

    ``outcome_ref`` names the DiD/B-gate/evidence-bundle result the pipeline
    produced; this workflow returns it as a reference and never inspects its
    internals (the B-verified-only intake boundary is w5-16's; the evidence
    bundle is w5-08's). A real implementation may of course carry an
    UNDETERMINED-shaped ref (insufficient/contaminated/late) — that is the
    pipeline's decision, opaque here.
    """

    outcome_ref: str


@runtime_checkable
class CollectAndDecidePort(Protocol):
    """The activity CONTRACT the timer-fire step calls.

    w5-13's real DiD → B-gate → evidence → outcome pipeline implements this
    (registered as the ``collect_and_decide`` activity on the Worker); this unit
    ships only a deterministic fixture implementation for tests. The workflow
    depends on the NAME + this signature, never a concrete class — so the real
    pipeline drops in without a workflow-code change.
    """

    async def collect_and_decide(
        self, activity_input: CollectAndDecideInput
    ) -> CollectAndDecideResult: ...


@activity.defn
async def derive_window(activity_input: DeriveWindowInput) -> DeriveWindowResult:
    """Derive the measurement window from an accepted confirmation.

    Wraps ``start_measurement_window`` verbatim (no reimplementation of the
    Day-2 rule / window arithmetic). Returns a ``FrozenWindowRecord`` projection
    of the derived window, OR ``deployment_late=True`` when the domain returns
    ``Undetermined``. Pure domain call — no IO here in this unit's fixture form
    (a production revision that must fetch ``registration_view`` from a store
    would do so through the persistence port, w5-10, still returning this same
    result shape).
    """
    verdict = start_measurement_window(
        activity_input.accepted,
        activity_input.accepted.registration_view,
        policy=activity_input.policy,
    )
    if isinstance(verdict, Undetermined):
        return DeriveWindowResult(window=None, deployment_late=True)
    return DeriveWindowResult(window=FrozenWindowRecord.from_domain(verdict), deployment_late=False)


@dataclass
class FixtureCollectAndDecide:
    """Deterministic fixture implementation of ``CollectAndDecidePort``.

    Produces a stable, deterministic ``outcome_ref`` derived from the window's
    idempotency key — enough for the workflow integration tests to assert "the
    window closed and the collect-and-decide activity ran, returning a
    reference", WITHOUT depending on w5-13's real DiD/B-gate pipeline. Registered
    as the ``collect_and_decide`` activity on the test Worker.

    Heartbeats once (proving the heartbeat contract is live end-to-end, same as
    ``saena_orchestrator``'s stub activity) — a real implementation heartbeats
    repeatedly across its actual batch work.
    """

    async def collect_and_decide(
        self, activity_input: CollectAndDecideInput
    ) -> CollectAndDecideResult:
        activity.heartbeat("collect_and_decide: window closed", activity_input.idempotency_key)
        return CollectAndDecideResult(outcome_ref=f"outcome-ref:{activity_input.idempotency_key}")


#: The activity NAME the workflow schedules at timer fire. The workflow calls
#: by this string so any implementation of ``CollectAndDecidePort`` (the fixture
#: here, or w5-13's real pipeline) registered under this name is invoked without
#: a workflow-code change.
COLLECT_AND_DECIDE_ACTIVITY = "collect_and_decide"

_FIXTURE = FixtureCollectAndDecide()


@activity.defn(name=COLLECT_AND_DECIDE_ACTIVITY)
async def collect_and_decide_fixture_activity(
    activity_input: CollectAndDecideInput,
) -> CollectAndDecideResult:
    """The fixture ``CollectAndDecidePort`` implementation as a ready-to-register
    ``@activity.defn`` under the stable ``COLLECT_AND_DECIDE_ACTIVITY`` name.

    The parameter is TYPED (``CollectAndDecideInput``) deliberately: the payload
    converter resolves the input type from this signature — an untyped wrapper
    would receive a raw ``dict`` and break the port contract. w5-13's real
    pipeline replaces this registration with its own implementation of the same
    name + signature; the workflow code does not change.
    """
    return await _FIXTURE.collect_and_decide(activity_input)


__all__ = [
    "COLLECT_AND_DECIDE_ACTIVITY",
    "CollectAndDecideInput",
    "CollectAndDecidePort",
    "CollectAndDecideResult",
    "DeriveWindowInput",
    "DeriveWindowResult",
    "FixtureCollectAndDecide",
    "FrozenWindowRecord",
    "HEARTBEAT_TIMEOUT_SECONDS",
    "collect_and_decide_fixture_activity",
    "derive_window",
]

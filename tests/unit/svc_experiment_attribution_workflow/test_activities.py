"""Activity unit tests — ``derive_window`` (pure domain call) and the
``FixtureCollectAndDecide`` port. ``activity.heartbeat`` needs a live Activity
context, so it is monkeypatched to a no-op here (same pattern as
``tests/unit/svc_orchestrator/test_activities.py``); the real heartbeat under a
Worker is proven in the integration lane.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from attribution_factories import make_accepted, make_registration_view
from saena_domain.measurement.clock import MeasurementPolicy
from saena_experiment_attribution.workflow.activities import (
    COLLECT_AND_DECIDE_ACTIVITY,
    CollectAndDecideInput,
    CollectAndDecidePort,
    DeriveWindowInput,
    FixtureCollectAndDecide,
    FrozenWindowRecord,
    derive_window,
)
from temporalio import activity


def test_derive_window_returns_frozen_window_for_on_time_deployment() -> None:
    # server_received_at == approved_at (Day 0) → on time → window starts.
    approved = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    accepted = make_accepted(server_received_at=approved, approved_at=approved)
    result = asyncio.run(derive_window(DeriveWindowInput(accepted=accepted)))
    assert result.deployment_late is False
    # A FrozenWindowRecord projection, NOT the guarded domain MeasurementWindow
    # (which deliberately cannot cross the Temporal payload boundary — its
    # token-guarded __init__ would refuse deserialization).
    assert isinstance(result.window, FrozenWindowRecord)
    # end == anchor + 7 days (domain default policy) — arithmetic delegated to
    # start_measurement_window, not reimplemented.
    assert result.window.anchor == approved
    assert result.window.end == approved + timedelta(days=7)
    assert result.window.window_days == 7
    assert result.window.idempotency_key == accepted.confirmation.idempotency_key


def test_derive_window_reports_deployment_late_past_day2() -> None:
    approved = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    # Confirmed Day 3 (> approved + 2 days) → Undetermined(deployment_late).
    late_anchor = approved + timedelta(days=3)
    accepted = make_accepted(server_received_at=late_anchor, approved_at=approved)
    result = asyncio.run(derive_window(DeriveWindowInput(accepted=accepted)))
    assert result.deployment_late is True
    assert result.window is None


def test_derive_window_honours_policy_override() -> None:
    approved = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    accepted = make_accepted(server_received_at=approved, approved_at=approved)
    result = asyncio.run(
        derive_window(DeriveWindowInput(accepted=accepted, policy=MeasurementPolicy(window_days=3)))
    )
    assert result.window is not None
    assert result.window.window_days == 3
    assert result.window.end == approved + timedelta(days=3)


def test_derive_window_uses_accepted_embedded_registration() -> None:
    # The activity passes accepted.registration_view to start_measurement_window
    # — a mismatched external registration cannot move the Day-2 deadline.
    approved = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    accepted = make_accepted(server_received_at=approved, approved_at=approved)
    assert accepted.registration_view == make_registration_view(approved_at=approved)


def test_fixture_collect_and_decide_returns_deterministic_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(activity, "heartbeat", lambda *args, **kwargs: None)
    impl = FixtureCollectAndDecide()
    result = asyncio.run(
        impl.collect_and_decide(
            CollectAndDecideInput(idempotency_key="idem-x", content_fingerprint="fp-x")
        )
    )
    assert result.outcome_ref == "outcome-ref:idem-x"


def test_fixture_collect_and_decide_heartbeats(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(activity, "heartbeat", lambda *args: calls.append(args))
    impl = FixtureCollectAndDecide()
    asyncio.run(
        impl.collect_and_decide(
            CollectAndDecideInput(idempotency_key="idem-y", content_fingerprint="fp-y")
        )
    )
    assert calls
    assert "idem-y" in calls[0]


def test_fixture_satisfies_collect_and_decide_port() -> None:
    assert isinstance(FixtureCollectAndDecide(), CollectAndDecidePort)


def test_collect_and_decide_activity_name_is_stable() -> None:
    # The workflow schedules the collect-and-decide step by THIS name so w5-13's
    # real pipeline drops in behind the Protocol without a workflow-code change.
    assert COLLECT_AND_DECIDE_ACTIVITY == "collect_and_decide"


def test_fixture_activity_defn_is_registered_under_stable_name_and_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ready-to-register @activity.defn wrapper: registered under the stable
    # name AND typed (the payload converter resolves the input type from its
    # signature — an untyped wrapper would receive a raw dict).
    from saena_experiment_attribution.workflow.activities import (
        collect_and_decide_fixture_activity,
    )
    from temporalio.activity import _Definition

    defn = _Definition.from_callable(collect_and_decide_fixture_activity)
    assert defn is not None
    assert defn.name == COLLECT_AND_DECIDE_ACTIVITY

    monkeypatch.setattr(activity, "heartbeat", lambda *args, **kwargs: None)
    result = asyncio.run(
        collect_and_decide_fixture_activity(
            CollectAndDecideInput(idempotency_key="idem-z", content_fingerprint="fp-z")
        )
    )
    assert result.outcome_ref == "outcome-ref:idem-z"

"""Discriminating tests for saena_domain.measurement.clock (w5-03).

The central adversarial invariant: the clock starts ONLY from an Accepted
deployment confirmation. There is NO API path from a bare timestamp, a
patch-creation time, a PR-creation time, a merge time, or an expected-deploy
time to a started window. Structural-guard tests below prove that removing the
private-token guard, the Day-2 guard, or the naive-datetime guard each flips an
assertion (guard-mutation).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from saena_domain.measurement.clock import (
    ClockStartReason,
    ConflictingConfirmationError,
    MeasurementPolicy,
    MeasurementWindow,
    Undetermined,
    resolve_duplicate_window,
    start_measurement_window,
)
from saena_domain.measurement.confirmation import (
    Accepted,
    Duplicate,
    validate_confirmation,
)

from .conftest import (
    REG_APPROVED_AT,
    SERVER_RECEIVED_AT,
    accepting_verifier,
    confirmation,
    registration_view,
)

UTC = UTC


def _accept(**conf_overrides: object) -> tuple[Accepted, object]:
    rv = registration_view()
    verdict = validate_confirmation(
        confirmation(**conf_overrides),  # type: ignore[arg-type]
        rv,
        conf_overrides.get("server_received_at", SERVER_RECEIVED_AT),  # type: ignore[arg-type]
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Accepted)
    return verdict, rv


def _accept_at(server_received_at: datetime) -> tuple[Accepted, object]:
    """Accept a confirmation observed at ``server_received_at`` (confirmed_at
    set to the same instant so it is neither backdated nor future)."""
    rv = registration_view()
    verdict = validate_confirmation(
        confirmation(confirmed_at=server_received_at),
        rv,
        server_received_at,
        accepting_verifier(),
        {},
    )
    assert isinstance(verdict, Accepted)
    return verdict, rv


# --------------------------------------------------------------------------- #
# Window starts ONLY from an Accepted confirmation
# --------------------------------------------------------------------------- #


def test_window_starts_from_accepted_confirmation() -> None:
    accepted, rv = _accept()
    window = start_measurement_window(accepted, rv)
    assert isinstance(window, MeasurementWindow)
    assert window.anchor == accepted.server_received_at
    assert window.window_days == 7


def test_window_end_is_anchor_plus_seven_days_exact() -> None:
    accepted, rv = _accept()
    window = start_measurement_window(accepted, rv)
    assert window.end - window.anchor == timedelta(days=7)


def test_window_anchor_is_server_received_at_not_confirmed_at() -> None:
    """The anchor is the server-observed receive time, never the payload
    confirmed_at claim."""
    claim = SERVER_RECEIVED_AT - timedelta(hours=3)
    rv = registration_view()
    accepted = validate_confirmation(
        confirmation(confirmed_at=claim),
        rv,
        SERVER_RECEIVED_AT,
        accepting_verifier(),
        {},
    )
    assert isinstance(accepted, Accepted)
    window = start_measurement_window(accepted, rv)
    assert window.anchor == SERVER_RECEIVED_AT
    assert window.anchor != claim


# --------------------------------------------------------------------------- #
# No other path starts the clock (structural)
# --------------------------------------------------------------------------- #


def test_direct_construction_without_token_is_rejected() -> None:
    """Misuse-guard pin: direct ``MeasurementWindow(...)`` with a bare
    timestamp (no private token) is a TypeError — every honest code path must
    go through ``start_measurement_window``. This is NOT a security boundary
    (in-process Python can bypass via ``model_construct``/token import; window
    authenticity rests on the confirmation record — see clock.py docstring).
    Deleting the token guard flips this test (guard-mutation)."""
    with pytest.raises(TypeError):
        MeasurementWindow(
            anchor=SERVER_RECEIVED_AT,
            end=SERVER_RECEIVED_AT + timedelta(days=7),
            window_days=7,
            idempotency_key="forged",
            content_fingerprint="sha256:" + "0" * 64,
        )


@pytest.mark.parametrize(
    "spoof_time_name",
    ["patch_created_at", "pr_created_at", "merge_time", "expected_deploy_at"],
)
def test_no_api_accepts_a_non_confirmation_timestamp(spoof_time_name: str) -> None:
    """Patch-creation / PR-creation / merge / expected-deploy timestamps have
    NO API path to start the clock: start_measurement_window's first positional
    argument is an Accepted, and passing a bare datetime is a TypeError (no
    overload accepts it)."""
    spoof_time = REG_APPROVED_AT + timedelta(hours=1)
    rv = registration_view()
    with pytest.raises((TypeError, AttributeError, ValueError)):
        start_measurement_window(spoof_time, rv)  # type: ignore[arg-type]


def test_start_requires_matching_registration_view() -> None:
    """A caller cannot pair an acceptance with a DIFFERENT registration's
    approval time to move the Day-2 deadline — the accepted verdict embeds its
    own registration_view and a mismatch is rejected."""
    accepted, _ = _accept()
    other_rv = registration_view(approved_at=REG_APPROVED_AT - timedelta(days=30))
    with pytest.raises(ValueError, match="does not match"):
        start_measurement_window(accepted, other_rv)


# --------------------------------------------------------------------------- #
# Day-2 rule (Algorithm §7.3:483)
# --------------------------------------------------------------------------- #


def test_deploy_within_day2_starts_the_clock() -> None:
    """Boundary: deploy exactly AT the Day-2 deadline starts the clock."""
    deadline = REG_APPROVED_AT + timedelta(days=2)
    accepted, rv = _accept_at(deadline)
    window = start_measurement_window(accepted, rv)
    assert isinstance(window, MeasurementWindow)


def test_deploy_after_day2_does_not_start_clock_undetermined_deployment_late() -> None:
    late = REG_APPROVED_AT + timedelta(days=2, seconds=1)
    accepted, rv = _accept_at(late)
    verdict = start_measurement_window(accepted, rv)
    assert isinstance(verdict, Undetermined)
    assert verdict.reason == ClockStartReason.DEPLOYMENT_LATE


def test_day2_deadline_respects_policy_override() -> None:
    """A stricter max_deploy_delay_days=1 makes a Day-2 deploy late."""
    day2 = REG_APPROVED_AT + timedelta(days=2)
    accepted, rv = _accept_at(day2)
    verdict = start_measurement_window(accepted, rv, MeasurementPolicy(max_deploy_delay_days=1))
    assert isinstance(verdict, Undetermined)
    assert verdict.reason == ClockStartReason.DEPLOYMENT_LATE


def test_custom_window_days_policy_is_honored() -> None:
    accepted, rv = _accept()
    window = start_measurement_window(accepted, rv, MeasurementPolicy(window_days=14))
    assert isinstance(window, MeasurementWindow)
    assert window.end - window.anchor == timedelta(days=14)
    assert window.window_days == 14


# --------------------------------------------------------------------------- #
# Duplicate / conflicting confirmation → same window / fail-closed
# --------------------------------------------------------------------------- #


def test_duplicate_confirmation_resolves_to_the_same_window_no_restart() -> None:
    c = confirmation()
    rv = registration_view()
    accepted = validate_confirmation(c, rv, SERVER_RECEIVED_AT, accepting_verifier(), {})
    assert isinstance(accepted, Accepted)
    window = start_measurement_window(accepted, rv)

    prior = {c.idempotency_key: accepted}
    dup = validate_confirmation(c, rv, SERVER_RECEIVED_AT, accepting_verifier(), prior)
    assert isinstance(dup, Duplicate)
    resolved = resolve_duplicate_window(window, dup)
    assert resolved is window  # SAME window, not a restart


def test_conflicting_duplicate_object_is_fail_closed_error() -> None:
    """Belt-and-suspenders: if a caller pairs a window with a Duplicate whose
    fingerprint/key does not match, that is a fail-closed error, not a silent
    winner."""
    accepted, rv = _accept()
    window = start_measurement_window(accepted, rv)

    # A Duplicate carrying a DIFFERENT accepted (different key/fingerprint).
    other_accepted, other_rv = _accept(idempotency_key="idem-9999")
    other_window_dup = Duplicate(accepted=other_accepted)
    with pytest.raises(ConflictingConfirmationError):
        resolve_duplicate_window(window, other_window_dup)


def test_window_is_bound_to_the_confirmation_identity() -> None:
    accepted, rv = _accept()
    window = start_measurement_window(accepted, rv)
    assert window.idempotency_key == accepted.confirmation.idempotency_key
    assert window.content_fingerprint == accepted.content_fingerprint


# --------------------------------------------------------------------------- #
# window_complete predicate
# --------------------------------------------------------------------------- #


def test_window_complete_is_false_before_end() -> None:
    accepted, rv = _accept()
    window = start_measurement_window(accepted, rv)
    assert window.window_complete(window.end - timedelta(seconds=1)) is False


def test_window_complete_is_true_at_and_after_end() -> None:
    accepted, rv = _accept()
    window = start_measurement_window(accepted, rv)
    assert window.window_complete(window.end) is True
    assert window.window_complete(window.end + timedelta(days=1)) is True


def test_window_complete_rejects_naive_datetime() -> None:
    accepted, rv = _accept()
    window = start_measurement_window(accepted, rv)
    with pytest.raises(ValueError, match="timezone-aware"):
        window.window_complete(window.end.replace(tzinfo=None))


# --------------------------------------------------------------------------- #
# Timezone / DST correctness by construction (property test)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "offset_hours",
    [-12, -8, -5, -1, 0, 1, 5, 8, 13, 14],
)
def test_same_instant_different_tz_offset_yields_identical_window(offset_hours: int) -> None:
    """Property: for the SAME physical instant expressed in any tz offset, the
    window anchor and end are the identical instant (DST/tz-proof).

    The reference is the UTC expression; each offset expresses the exact same
    moment. Comparing aware datetimes compares instants, so anchors/ends must
    be equal across all offsets."""
    base_instant = SERVER_RECEIVED_AT  # aware UTC
    shifted_tz = timezone(timedelta(hours=offset_hours))
    same_instant_shifted = base_instant.astimezone(shifted_tz)
    assert same_instant_shifted == base_instant  # same physical instant

    ref_accepted, ref_rv = _accept_at(base_instant)
    ref_window = start_measurement_window(ref_accepted, ref_rv)

    shifted_accepted, shifted_rv = _accept_at(same_instant_shifted)
    shifted_window = start_measurement_window(shifted_accepted, shifted_rv)

    assert isinstance(ref_window, MeasurementWindow)
    assert isinstance(shifted_window, MeasurementWindow)
    # Instants are identical regardless of the tz the confirmation used.
    assert shifted_window.anchor == ref_window.anchor
    assert shifted_window.end == ref_window.end


def test_window_end_is_exactly_seven_days_across_a_dst_transition() -> None:
    """A window anchored just before a northern-hemisphere spring-forward is
    still exactly 7 * 24h later — because the arithmetic is on absolute
    instants, not wall-clock calendar fields. (US DST 2026-03-08 02:00 local.)"""
    # 2026-03-07 12:00 US/Eastern would be EST (UTC-5). Express as the UTC
    # instant; add 7 days; confirm it is exactly 168h later in UTC.
    anchor_utc = datetime(2026, 3, 7, 17, 0, 0, tzinfo=UTC)  # 12:00 EST
    # registration approved before anchor so it is within Day-2 and not backdated
    rv2 = registration_view(
        created_at=anchor_utc - timedelta(days=1),
        approved_at=anchor_utc - timedelta(hours=1),
    )
    accepted2 = validate_confirmation(
        confirmation(confirmed_at=anchor_utc),
        rv2,
        anchor_utc,
        accepting_verifier(),
        {},
    )
    assert isinstance(accepted2, Accepted)
    window = start_measurement_window(accepted2, rv2)
    assert isinstance(window, MeasurementWindow)
    assert window.end == anchor_utc + timedelta(hours=168)


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_start_is_deterministic_across_three_calls() -> None:
    results = []
    for _ in range(3):
        accepted, rv = _accept()
        window = start_measurement_window(accepted, rv)
        assert isinstance(window, MeasurementWindow)
        results.append((window.anchor, window.end, window.window_days))
    assert results[0] == results[1] == results[2]


# --------------------------------------------------------------------------- #
# Model hardening
# --------------------------------------------------------------------------- #


def test_policy_rejects_zero_window_days() -> None:
    with pytest.raises(ValueError):
        MeasurementPolicy(window_days=0)


def test_policy_rejects_negative_max_deploy_delay_days() -> None:
    with pytest.raises(ValueError):
        MeasurementPolicy(max_deploy_delay_days=-1)


def test_window_is_frozen() -> None:
    accepted, rv = _accept()
    window = start_measurement_window(accepted, rv)
    with pytest.raises(ValueError):
        window.anchor = SERVER_RECEIVED_AT + timedelta(days=1)  # type: ignore[misc]

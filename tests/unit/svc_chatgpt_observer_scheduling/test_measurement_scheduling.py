"""w5-15 measurement observation scheduling / rate-policy boundary tests.

Covers the eight required test families:
- determinism (same inputs → identical schedule 2×)
- arm balance under odd repeat counts
- ROLLING per-day rate limit never exceeded in any sliding 24h slice
  (property-style, with a BINDING small cap — critic remediation)
- backoff monotonic (then reset, no jitter)
- concurrent-session quota respected (lane model + documented precondition)
- fixture-observer replay stable
- no-network-import guard (honest source-level scan; mutation-verified)
- imbalance-cap enforcement (defense-in-depth; build() path is always
  balanced today — see module "Arm balancing note")
plus the fail-closed boundary guards (incomplete cell / bad window / bad
policy / production-without-well-formed-approval-token, per-slot AND
per-schedule fixture-provenance guards).
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict

import pytest
from saena_chatgpt_observer.measurement_scheduling import (
    APPROVAL_TOKEN_PREFIX,
    FORBIDDEN_IMPORT_PREFIXES,
    ApprovedFixtureObserver,
    Arm,
    MeasurementWindow,
    ObservationCell,
    ObservationCellSchedule,
    Provenance,
    RatePolicy,
    SchedulingApprovalRequiredError,
    SchedulingBoundaryError,
    SchedulingRatePolicyError,
    SchedulingWindowError,
)

# One day in seconds — window/rate arithmetic reference (mirrors conftest.DAY_S).
DAY_S = 86_400

VALID_TOKEN = APPROVAL_TOKEN_PREFIX + "issued-by-a-human-2026-07-14"


def _build(cell, window, policy, **kw):
    return ObservationCellSchedule.build(cell=cell, window=window, policy=policy, **kw)


def _cell(**overrides) -> ObservationCell:
    base = dict(
        query_cluster_ref="c://x",
        locale="en",
        browser_policy="p",
        repeat_count=2,
        domain_key="d",
    )
    base.update(overrides)
    return ObservationCell(**base)


def _policy(**overrides) -> RatePolicy:
    base = dict(
        max_per_day=1_000,
        max_concurrent=3,
        min_gap_seconds=60,
        backoff_base_seconds=2,
        backoff_factor=2,
        backoff_cap_seconds=30,
        max_retries=4,
        imbalance_ratio_cap=2.0,
    )
    base.update(overrides)
    return RatePolicy(**base)


# --------------------------------------------------------------------------
# Happy path shape
# --------------------------------------------------------------------------
def test_build_produces_repeat_count_times_three_slots(cell, window, policy):
    schedule = _build(cell, window, policy)
    assert len(schedule.slots) == cell.repeat_count * 3
    assert all(isinstance(s.arm, Arm) for s in schedule.slots)
    assert all(s.provenance is Provenance.FIXTURE for s in schedule.slots)


def test_every_slot_carries_registration_fields(cell, window, policy):
    schedule = _build(cell, window, policy)
    for slot in schedule.slots:
        assert slot.query_cluster_ref == cell.query_cluster_ref
        assert slot.locale == cell.locale
        assert slot.browser_policy == cell.browser_policy
        assert slot.domain_key == cell.domain_key


def test_slots_scheduled_inside_window(cell, window, policy):
    schedule = _build(cell, window, policy)
    for slot in schedule.slots:
        assert window.start_epoch_s <= slot.scheduled_at_epoch_s <= window.end_epoch_s


def test_consecutive_slots_spaced_exactly_one_stride(cell, window, policy):
    schedule = _build(cell, window, policy)
    stride = policy.slot_stride_seconds
    times = [s.scheduled_at_epoch_s for s in schedule.slots]
    for earlier, later in zip(times, times[1:], strict=False):
        assert later - earlier == stride


def test_slot_stride_is_max_of_min_gap_and_day_stride():
    # day stride binds: ceil(86400/1000)=87 > min_gap 60
    assert _policy(max_per_day=1_000, min_gap_seconds=60).slot_stride_seconds == 87
    # min_gap binds: ceil(86400/10000)=9 < min_gap 60
    assert _policy(max_per_day=10_000, min_gap_seconds=60).slot_stride_seconds == 60
    # exact division: 86400/3 = 28800
    assert _policy(max_per_day=3, min_gap_seconds=60).slot_stride_seconds == 28_800


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------
def test_determinism_identical_schedule_twice(cell, window, policy):
    a = _build(cell, window, policy)
    b = _build(cell, window, policy)
    assert a.slots == b.slots


def test_determinism_across_fresh_value_objects():
    # Rebuild the inputs from scratch — schedule must be byte-identical.
    policy = _policy()
    a = _build(
        _cell(locale="ko-KR", repeat_count=5),
        MeasurementWindow(start_epoch_s=10, end_epoch_s=10 + DAY_S),
        policy,
    )
    b = _build(
        _cell(locale="ko-KR", repeat_count=5),
        MeasurementWindow(start_epoch_s=10, end_epoch_s=10 + DAY_S),
        _policy(),
    )
    assert a.slots == b.slots


# --------------------------------------------------------------------------
# Arm balance under odd repeat counts
# --------------------------------------------------------------------------
@pytest.mark.parametrize("repeat_count", [1, 2, 3, 5, 7, 11, 13])
def test_arm_balance_off_by_at_most_one(repeat_count, policy):
    window = MeasurementWindow(start_epoch_s=0, end_epoch_s=7 * DAY_S)
    schedule = _build(_cell(repeat_count=repeat_count), window, policy)
    counts = schedule.arm_counts()
    assert sum(counts.values()) == repeat_count * 3
    assert max(counts.values()) - min(counts.values()) <= 1


def test_arm_counts_match_slots_for_arm(cell, window, policy):
    schedule = _build(cell, window, policy)
    for arm in Arm:
        assert len(schedule.slots_for_arm(arm)) == schedule.arm_counts()[arm]


# --------------------------------------------------------------------------
# Imbalance-cap enforcement (defense-in-depth — the build() path always
# produces equal arms today because total = repeat_count * 3 is divisible by
# 3; the module docstring's "Arm balancing note" discloses this honestly.
# These tests (a) pin the balanced-build invariant under the tightest cap and
# (b) exercise the guard DIRECTLY with synthetic uneven arms so removing it
# fails a test (guard-mutation target for the future arm-weighting path).
# --------------------------------------------------------------------------
def test_tightest_cap_admits_balanced_build(window):
    schedule = _build(_cell(repeat_count=1), window, _policy(imbalance_ratio_cap=1.0))
    counts = schedule.arm_counts()
    assert max(counts.values()) == min(counts.values())


def test_imbalance_cap_below_one_rejected_by_policy_validate():
    with pytest.raises(SchedulingRatePolicyError, match="imbalance_ratio_cap"):
        _policy(imbalance_ratio_cap=0.5).validate()


def test_imbalance_guard_fires_on_synthetic_uneven_arms(policy):
    from saena_chatgpt_observer.measurement_scheduling import _guard_imbalance

    uneven = [Arm.BASELINE, Arm.BASELINE, Arm.BASELINE, Arm.CONTROL]
    tight = dataclasses.replace(policy, imbalance_ratio_cap=1.0)
    with pytest.raises(SchedulingRatePolicyError, match="imbalance ratio"):
        _guard_imbalance(uneven, tight)


def test_imbalance_guard_empty_is_noop(policy):
    from saena_chatgpt_observer.measurement_scheduling import _guard_imbalance

    _guard_imbalance([], policy)  # no raise


# --------------------------------------------------------------------------
# ROLLING per-day rate limit — BINDING small caps (critic MUST-FIX)
# --------------------------------------------------------------------------
def _sliding_24h_max(times: list[int]) -> int:
    """Max slot count over every half-open 24h interval [t, t+DAY_S).

    For point events the maximum over all sliding anchors is attained when
    the window starts exactly at some slot time, so checking each slot time
    as an anchor is exhaustive."""
    times = sorted(times)
    return max(sum(1 for t in times if anchor <= t < anchor + DAY_S) for anchor in times)


def test_critic_repro_max_per_day_3_three_day_window_repeat_3():
    # Critic MUST-FIX repro: max_per_day=3, 3-day window, repeat_count=3 →
    # previously all 9 slots packed min_gap apart inside a single 24h span
    # (worst rolling window = 9 > 3). Now stride = ceil(86400/3) = 28800 →
    # any sliding 24h slice holds at most 3.
    window = MeasurementWindow(start_epoch_s=0, end_epoch_s=3 * DAY_S)
    policy = _policy(max_per_day=3)
    schedule = _build(_cell(repeat_count=3), window, policy)
    times = [s.scheduled_at_epoch_s for s in schedule.slots]
    assert len(times) == 9
    assert _sliding_24h_max(times) <= 3


@pytest.mark.parametrize(
    ("max_per_day", "repeat_count", "days"),
    [(1, 1, 3), (2, 2, 3), (3, 3, 3), (5, 5, 3), (4, 3, 3), (7, 6, 3)],
)
def test_rolling_day_cap_never_exceeded_any_slice_binding(max_per_day, repeat_count, days):
    # BINDING caps (small values — the cap, not the window, is the tight
    # constraint), multi-day window, sliding half-open 24h check anchored at
    # every slot time (exhaustive for point events). Also anchor at slot
    # times shifted across the day boundary via t-1 probes.
    window = MeasurementWindow(start_epoch_s=0, end_epoch_s=days * DAY_S)
    policy = _policy(max_per_day=max_per_day)
    schedule = _build(_cell(repeat_count=repeat_count), window, policy)
    times = sorted(s.scheduled_at_epoch_s for s in schedule.slots)
    assert _sliding_24h_max(times) <= max_per_day
    # extra straddling probes: windows starting 1s before each slot
    for anchor in times:
        count = sum(1 for t in times if anchor - 1 <= t < anchor - 1 + DAY_S)
        assert count <= max_per_day


def test_day_boundary_straddling_window_cannot_exceed_cap():
    # Explicit anti-calendar-bucket check: a 24h window straddling the
    # boundary between day 1 and day 2 must also hold <= max_per_day.
    window = MeasurementWindow(start_epoch_s=0, end_epoch_s=2 * DAY_S)
    policy = _policy(max_per_day=2)
    schedule = _build(_cell(repeat_count=1), window, policy)  # 3 slots
    times = sorted(s.scheduled_at_epoch_s for s in schedule.slots)
    # probe anchors every stride/2 across the whole span
    stride = policy.slot_stride_seconds
    anchors = range(0, 2 * DAY_S, stride // 2)
    for anchor in anchors:
        count = sum(1 for t in times if anchor <= t < anchor + DAY_S)
        assert count <= 2


def test_rate_limit_exceeded_fails_closed():
    # Tiny window vs. many slots → must reject, never silently truncate.
    window = MeasurementWindow(start_epoch_s=0, end_epoch_s=120)
    policy = _policy(max_per_day=1_000, max_concurrent=1, min_gap_seconds=60)
    # stride = max(60, 87) = 87; capacity = 120//87 + 1 = 2 < 12 slots.
    with pytest.raises(SchedulingRatePolicyError, match="exceed schedulable capacity"):
        _build(_cell(repeat_count=4), window, policy)


def test_per_day_cap_binds_capacity_when_lower_than_min_gap_density():
    # max_per_day=5 → stride 17280 dominates min_gap 60; 9 slots need
    # 8*17280 = 138240 > 86400 → reject.
    window = MeasurementWindow(start_epoch_s=0, end_epoch_s=DAY_S)
    policy = _policy(max_per_day=5)
    with pytest.raises(SchedulingRatePolicyError, match="exceed schedulable capacity"):
        _build(_cell(repeat_count=3), window, policy)


def test_gap_larger_than_window_rejected():
    # min_gap larger than the whole window → capacity 1 < 3 slots → reject
    # (fail closed, never squeezed).
    window = MeasurementWindow(start_epoch_s=0, end_epoch_s=DAY_S)
    policy = _policy(min_gap_seconds=DAY_S + 1)
    with pytest.raises(SchedulingRatePolicyError, match="exceed schedulable capacity"):
        _build(_cell(repeat_count=1), window, policy)


# --------------------------------------------------------------------------
# Concurrency quota respected (lane model + documented runtime precondition:
# the "at most max_concurrent in flight" bound holds provided each
# observation's runtime <= max_concurrent * slot_stride_seconds — enforcement
# of that runtime budget is the executing caller's job, per RatePolicy docs).
# --------------------------------------------------------------------------
@pytest.mark.parametrize("max_concurrent", [1, 2, 3, 5])
def test_lane_indexes_bounded_and_round_robin(max_concurrent):
    window = MeasurementWindow(start_epoch_s=0, end_epoch_s=DAY_S)
    policy = _policy(max_per_day=10_000, max_concurrent=max_concurrent)
    schedule = _build(_cell(repeat_count=7), window, policy)
    assert all(0 <= s.lane < max_concurrent for s in schedule.slots)
    for s in schedule.slots:
        assert s.lane == s.slot_index % max_concurrent
    # No instant is covered by more slots (on distinct lanes) than the quota.
    at_instant: dict[int, set[int]] = defaultdict(set)
    for s in schedule.slots:
        at_instant[s.scheduled_at_epoch_s].add(s.lane)
    for lanes in at_instant.values():
        assert len(lanes) <= max_concurrent


def test_same_lane_slots_lane_period_apart(cell, window, policy):
    schedule = _build(cell, window, policy)
    stride = policy.slot_stride_seconds
    lane_period = policy.max_concurrent * stride
    by_lane: dict[int, list[int]] = {}
    for s in schedule.slots:
        by_lane.setdefault(s.lane, []).append(s.scheduled_at_epoch_s)
    for times in by_lane.values():
        times.sort()
        for earlier, later in zip(times, times[1:], strict=False):
            assert later - earlier == lane_period
            assert later - earlier >= policy.min_gap_seconds


def test_min_gap_respected_between_any_consecutive_slots(cell, window, policy):
    schedule = _build(cell, window, policy)
    times = sorted(s.scheduled_at_epoch_s for s in schedule.slots)
    for earlier, later in zip(times, times[1:], strict=False):
        assert later - earlier >= policy.min_gap_seconds


# --------------------------------------------------------------------------
# Backoff monotonic (then reset, no jitter)
# --------------------------------------------------------------------------
def test_backoff_stagger_monotonic_within_a_reset_cycle(policy):
    period = policy.max_retries + 1
    staggers = [policy.backoff_stagger_for(i) for i in range(period)]
    for earlier, later in zip(staggers, staggers[1:], strict=False):
        assert later >= earlier


def test_backoff_stagger_deterministic_no_jitter(policy):
    for i in range(20):
        assert policy.backoff_stagger_for(i) == policy.backoff_stagger_for(i)


def test_backoff_stagger_clamped_to_cap(policy):
    for i in range(100):
        assert policy.backoff_stagger_for(i) <= policy.backoff_cap_seconds


def test_backoff_resets_each_cycle(policy):
    period = policy.max_retries + 1
    assert policy.backoff_stagger_for(0) == policy.backoff_stagger_for(period)
    assert policy.backoff_stagger_for(1) == policy.backoff_stagger_for(period + 1)


def test_backoff_zero_retries_is_constant():
    policy = _policy(backoff_base_seconds=3, max_retries=0)
    values = {policy.backoff_stagger_for(i) for i in range(10)}
    assert values == {3}


# --------------------------------------------------------------------------
# Fixture observer replay stable
# --------------------------------------------------------------------------
def test_fixture_observer_replay_stable(cell, window, policy):
    schedule = _build(cell, window, policy)
    obs = ApprovedFixtureObserver()
    obs.register(
        query_cluster_ref=cell.query_cluster_ref,
        locale=cell.locale,
        citation_refs=("cite://a", "cite://b"),
        raw_object_ref="artifact://acme/deadbeef",
    )
    first = obs.replay_schedule(schedule)
    second = obs.replay_schedule(schedule)
    assert first == second
    assert len(first) == len(schedule.slots)
    assert all(o.provenance is Provenance.FIXTURE for o in first)
    assert all(o.citation_refs == ("cite://a", "cite://b") for o in first)


def test_fixture_observer_records_calls(cell, window, policy):
    schedule = _build(cell, window, policy)
    obs = ApprovedFixtureObserver()
    obs.register(
        query_cluster_ref=cell.query_cluster_ref,
        locale=cell.locale,
        citation_refs=(),
        raw_object_ref="artifact://acme/x",
    )
    obs.replay_schedule(schedule)
    assert obs.observe_calls == [s.slot_index for s in schedule.slots]


def test_fixture_observer_missing_fixture_fails_closed(cell, window, policy):
    schedule = _build(cell, window, policy)
    obs = ApprovedFixtureObserver()  # nothing registered
    with pytest.raises(SchedulingBoundaryError, match="no approved fixture"):
        obs.replay_schedule(schedule)


def test_fixture_observer_refuses_production_schedule(cell, window, policy):
    schedule = _build(
        cell,
        window,
        policy,
        provenance=Provenance.PRODUCTION,
        production_approval_token=VALID_TOKEN,
    )
    obs = ApprovedFixtureObserver()
    with pytest.raises(SchedulingApprovalRequiredError, match="only replays fixture"):
        obs.replay_schedule(schedule)


def test_observe_slot_refuses_production_slot(cell, window, policy):
    # Per-slot guard, symmetric with the whole-schedule guard (critic
    # should-fix 2): a single production-provenance slot handed directly to
    # observe_slot is refused before any fixture lookup or call recording.
    schedule = _build(
        cell,
        window,
        policy,
        provenance=Provenance.PRODUCTION,
        production_approval_token=VALID_TOKEN,
    )
    obs = ApprovedFixtureObserver()
    obs.register(
        query_cluster_ref=cell.query_cluster_ref,
        locale=cell.locale,
        citation_refs=(),
        raw_object_ref="artifact://acme/x",
    )
    with pytest.raises(SchedulingApprovalRequiredError, match="only serves fixture"):
        obs.observe_slot(schedule.slots[0])
    assert obs.observe_calls == []  # refused before recording


def test_observe_slot_zero_citations_valid(cell, window, policy):
    schedule = _build(cell, window, policy)
    obs = ApprovedFixtureObserver()
    obs.register(
        query_cluster_ref=cell.query_cluster_ref,
        locale=cell.locale,
        citation_refs=(),
        raw_object_ref="artifact://acme/empty",
    )
    result = obs.observe_slot(schedule.slots[0])
    assert result.citation_refs == ()
    assert result.provenance is Provenance.FIXTURE


# --------------------------------------------------------------------------
# No-network-import guard — HONEST SCOPE: a direct source-level text scan of
# the module's (and its first-party `errors` dependency's) import statements.
# NOT a transitive third-party import-graph analysis. Mutation-verified:
# injecting a forbidden import into the module makes this test fail.
# --------------------------------------------------------------------------
def test_module_and_first_party_deps_import_no_network_or_browser_library():
    import importlib
    import sys

    module_names = (
        "saena_chatgpt_observer.measurement_scheduling",
        "saena_chatgpt_observer.errors",  # this module's only first-party import
    )
    for modname in module_names:
        importlib.import_module(modname)
        mod = sys.modules[modname]
        src = mod.__loader__.get_source(modname)  # type: ignore[union-attr]
        assert src is not None
        for banned in FORBIDDEN_IMPORT_PREFIXES:
            assert f"import {banned}" not in src, (modname, banned)
            assert f"from {banned}" not in src, (modname, banned)


def test_forbidden_prefixes_cover_stdlib_and_thirdparty_clients():
    # Denylist breadth (critic should-fix 1): stdlib socket/url/http/ftp
    # clients AND the common third-party HTTP/browser libraries.
    for required in (
        "socket",
        "urllib",
        "http.client",
        "ftplib",
        "requests",
        "aiohttp",
        "httpx",
        "playwright",
        "selenium",
    ):
        assert required in FORBIDDEN_IMPORT_PREFIXES


def test_fixture_observer_has_no_write_or_fetch_surface():
    surface = set(dir(ApprovedFixtureObserver))
    for banned in (
        "fetch",
        "navigate",
        "get",
        "post",
        "login",
        "submit",
        "request",
        "send",
        "connect",
        "write",
    ):
        assert banned not in surface


# --------------------------------------------------------------------------
# Boundary guards — incomplete cell
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "overrides",
    [
        {"query_cluster_ref": ""},
        {"locale": ""},
        {"browser_policy": ""},
        {"domain_key": ""},
    ],
)
def test_incomplete_cell_string_field_rejected(overrides, window, policy):
    with pytest.raises(SchedulingBoundaryError, match="must be a non-empty"):
        _build(_cell(**overrides), window, policy)


def test_repeat_count_zero_rejected(window, policy):
    with pytest.raises(SchedulingBoundaryError, match="repeat_count must be >= 1"):
        _build(_cell(repeat_count=0), window, policy)


def test_repeat_count_non_int_rejected(window, policy):
    with pytest.raises(SchedulingBoundaryError, match="repeat_count must be an int"):
        _build(_cell(repeat_count=True), window, policy)


# --------------------------------------------------------------------------
# Boundary guards — window
# --------------------------------------------------------------------------
def test_inverted_window_rejected(cell, policy):
    win = MeasurementWindow(start_epoch_s=100, end_epoch_s=100)  # end == start
    with pytest.raises(SchedulingWindowError, match="must be strictly after"):
        _build(cell, win, policy)


def test_window_non_int_rejected(cell, policy):
    win = MeasurementWindow(start_epoch_s=1.5, end_epoch_s=100)  # type: ignore[arg-type]
    with pytest.raises(SchedulingWindowError, match="whole seconds"):
        _build(cell, win, policy)


def test_window_bool_rejected(cell, policy):
    win = MeasurementWindow(start_epoch_s=True, end_epoch_s=100)  # type: ignore[arg-type]
    with pytest.raises(SchedulingWindowError, match="whole seconds"):
        _build(cell, win, policy)


def test_window_duration_property():
    win = MeasurementWindow(start_epoch_s=10, end_epoch_s=70)
    assert win.duration_s == 60


# --------------------------------------------------------------------------
# Boundary guards — policy validation
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "field_name",
    [
        "max_per_day",
        "max_concurrent",
        "min_gap_seconds",
        "backoff_base_seconds",
        "backoff_factor",
        "backoff_cap_seconds",
    ],
)
def test_policy_positive_int_fields_rejected_when_nonpositive(field_name):
    with pytest.raises(SchedulingRatePolicyError, match="must be a positive int"):
        _policy(**{field_name: 0}).validate()


def test_policy_negative_max_retries_rejected():
    with pytest.raises(SchedulingRatePolicyError, match="max_retries must be >= 0"):
        _policy(max_retries=-1).validate()


def test_policy_max_retries_non_int_rejected():
    with pytest.raises(SchedulingRatePolicyError, match="max_retries must be an int"):
        _policy(max_retries=1.5).validate()  # type: ignore[arg-type]


def test_policy_cap_below_base_rejected():
    with pytest.raises(SchedulingRatePolicyError, match="backoff_cap_seconds"):
        _policy(backoff_base_seconds=30, backoff_cap_seconds=10).validate()


def test_policy_imbalance_cap_non_number_rejected():
    with pytest.raises(SchedulingRatePolicyError, match="imbalance_ratio_cap"):
        _policy(imbalance_ratio_cap="loose").validate()  # type: ignore[arg-type]


def test_policy_imbalance_cap_bool_rejected():
    with pytest.raises(SchedulingRatePolicyError, match="imbalance_ratio_cap"):
        _policy(imbalance_ratio_cap=True).validate()  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Boundary guards — production provenance requires a WELL-FORMED human
# approval token (mechanism-only placeholder: shape check, fail-closed; the
# scheduler never mints/verifies one — critic should-fix 5)
# --------------------------------------------------------------------------
def test_production_provenance_without_token_fails_closed(cell, window, policy):
    with pytest.raises(SchedulingApprovalRequiredError, match="human approval token"):
        _build(cell, window, policy, provenance=Provenance.PRODUCTION)


def test_production_provenance_empty_token_fails_closed(cell, window, policy):
    with pytest.raises(SchedulingApprovalRequiredError):
        _build(
            cell,
            window,
            policy,
            provenance=Provenance.PRODUCTION,
            production_approval_token="",
        )


def test_production_provenance_wrong_shape_token_fails_closed(cell, window, policy):
    # Non-empty but missing the required structured prefix → still DENY.
    with pytest.raises(SchedulingApprovalRequiredError, match="human-approval:"):
        _build(
            cell,
            window,
            policy,
            provenance=Provenance.PRODUCTION,
            production_approval_token="some-random-string",
        )


def test_production_provenance_prefix_only_token_fails_closed(cell, window, policy):
    # The prefix alone (empty payload) is malformed → DENY.
    with pytest.raises(SchedulingApprovalRequiredError):
        _build(
            cell,
            window,
            policy,
            provenance=Provenance.PRODUCTION,
            production_approval_token=APPROVAL_TOKEN_PREFIX,
        )


def test_production_provenance_non_string_token_fails_closed(cell, window, policy):
    with pytest.raises(SchedulingApprovalRequiredError):
        _build(
            cell,
            window,
            policy,
            provenance=Provenance.PRODUCTION,
            production_approval_token=12345,  # type: ignore[arg-type]
        )


def test_production_provenance_with_wellformed_token_builds(cell, window, policy):
    # Mechanism only: shape-valid token → the mechanism proceeds and stamps
    # provenance=production on the slots. A REAL approval is a human act;
    # this placeholder never verifies issuance.
    schedule = _build(
        cell,
        window,
        policy,
        provenance=Provenance.PRODUCTION,
        production_approval_token=VALID_TOKEN,
    )
    assert all(s.provenance is Provenance.PRODUCTION for s in schedule.slots)


def test_fixture_provenance_needs_no_token(cell, window, policy):
    schedule = _build(cell, window, policy, provenance=Provenance.FIXTURE)
    assert all(s.provenance is Provenance.FIXTURE for s in schedule.slots)


# --------------------------------------------------------------------------
# Enum spellings (contract stability)
# --------------------------------------------------------------------------
def test_arm_and_provenance_enum_values():
    assert {a.value for a in Arm} == {"baseline", "treatment", "control"}
    assert {p.value for p in Provenance} == {"fixture", "production"}

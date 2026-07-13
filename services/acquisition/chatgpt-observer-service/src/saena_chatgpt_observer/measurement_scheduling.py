"""`measurement_scheduling` — w5-15 observation scheduling / rate-policy
boundary for measurement cells (approved-fixture adapter ONLY).

This module is PURE LOGIC + a fixture adapter. It performs NO real network or
browser I/O and — by design — pulls in NO network/browser library (`httpx`,
`playwright`, `requests`, sockets, url-fetching stdlib clients, ...). A unit
test enforces this with a DIRECT SOURCE-LEVEL IMPORT SCAN of this module and
its first-party `saena_chatgpt_observer` dependency (`errors`) — an honest,
mechanical text scan of import statements, NOT a transitive import-graph
analysis (third-party transitive closure is out of that guard's scope; the
real Playwright driver lives in `playwright_driver.py`, integration-lane only,
and is never reached from here). Production external observation is FORBIDDEN
in Wave 5 (wave5-plan.md Non-scope: "live customer observation / real ChatGPT
calls"); the only observer this module ships is `ApprovedFixtureObserver`,
which replays approved fixture observations deterministically and stamps
`provenance=fixture`.

What w5-15 delivers, given an already-*registered* observation cell (its
`query_cluster_ref` / `locale` / `browser_policy` / `repeat_count` are bound
upstream by w5-04's experiment→measurement binding — this module NEVER invents
them, it only validates the caller supplied a complete cell) plus a
measurement window and a `RatePolicy`:

1. `ObservationCellSchedule.build(...)` — a DETERMINISTIC schedule of
   observation slots laid across the window, split across the
   baseline/treatment/control arms with a bounded imbalance ratio, honouring:

   - **rolling per-day rate limit**: consecutive slots are spaced a uniform
     `slot_stride_seconds = max(min_gap_seconds, ceil(86400 / max_per_day))`
     apart, so ANY half-open 24-hour interval `[t, t+86400)` contains at most
     `max_per_day` slots for the cell's domain — by construction, for every
     sliding anchor `t`, including anchors straddling a calendar-day boundary
     (never a calendar-bucket heuristic);
   - **minimum gap**: `slot_stride_seconds >= min_gap_seconds` always;
   - **concurrent-session quota**: slot `i` is bookkept on lane
     `i % max_concurrent`; two slots on the SAME lane start
     `max_concurrent * slot_stride_seconds` apart. DOCUMENTED PRECONDITION
     (not a runtime measurement — this module schedules instants, it does not
     execute observations): at most `max_concurrent` observations are ever in
     flight PROVIDED each observation's runtime is at most
     `max_concurrent * slot_stride_seconds`; if each runtime is at most
     `min_gap_seconds`, in-flight concurrency is at most 1. The executing
     caller (w5-14 workflow / k3s Job budget, M9/M10) owns enforcing that
     runtime budget;
   - **deterministic backoff**: a per-slot exponential retry stagger derived
     purely from the slot index (NO random jitter). Same inputs →
     byte-identical schedule on every call/process/machine.

2. `RatePolicy` — a frozen mechanism-only model. Every field is caller-injected
   (a TEST-ONLY fixture in the unit lane); this module hardcodes NO production
   rate values, quotas, or imbalance caps. Production rate/quota/imbalance
   policy is a human decision (wave5-plan.md H2 "ChatGPT obs methodology/rate/
   ToS owner (§13-1) — owner assignment, live obs BLOCKED"), never baked in
   here.

3. `ApprovedFixtureObserver` — the service's observation port implemented for
   tests by replaying approved fixture observations; `provenance=fixture`;
   structurally cannot reach the network; refuses (per slot AND per schedule)
   to serve anything but fixture provenance.

4. Boundary guard — `ObservationCellSchedule.build` refuses an incomplete cell
   (any of the four registration fields missing/blank, or a non-positive
   `repeat_count`), refuses a window-less / inverted / non-integer window,
   refuses an out-of-range policy, and refuses to emit
   `provenance=production` slots without a well-formed human approval token
   (`human-approval:<non-empty>` — a fail-closed, MECHANISM-ONLY placeholder
   protocol: this code validates the token's SHAPE and never mints, verifies,
   or grants one; a real production approval is a HUMAN decision, BLOCKED in
   Wave 5).

Arm balancing note (honest dead-code disclosure): arms are assigned round-robin
over exactly 3 arms and the slot total is always `repeat_count * 3`, so the
`build()` path always produces perfectly equal arms — the imbalance-ratio
guard can NEVER fire from `build()` today. It is kept as defense-in-depth for
a future arm-weighting change (e.g. per-arm repeat counts) and is exercised
directly by a unit test against synthetic uneven arm lists; the
`imbalance_ratio_cap` policy field remains the binding contract for that
future path.

Determinism discipline mirrors `capture.py`'s injectable-clock convention and
`pool_capture.py`'s injectable id-factory: there is no wall-clock read and no
`random` anywhere in this module — every scheduled instant and every backoff
stagger is a pure function of (window, policy, slot index).
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass

from saena_chatgpt_observer.errors import ChatgptObserverError

__all__ = [
    "APPROVAL_TOKEN_PREFIX",
    "ApprovedFixtureObserver",
    "Arm",
    "FixtureObservation",
    "MeasurementWindow",
    "ObservationCell",
    "ObservationCellSchedule",
    "ObservationSlot",
    "Provenance",
    "RatePolicy",
    "SchedulingApprovalRequiredError",
    "SchedulingBoundaryError",
    "SchedulingRatePolicyError",
    "SchedulingWindowError",
]

_SECONDS_PER_DAY = 86_400

#: Required shape prefix for the production-approval placeholder token.
#: MECHANISM ONLY: this module validates a presented token's SHAPE
#: (`human-approval:<non-empty>`) and fails closed otherwise; it never mints,
#: signs, verifies, or grants a token — issuing one is a HUMAN act outside
#: this codebase (wave5-plan.md H2, production observation BLOCKED(human)).
APPROVAL_TOKEN_PREFIX = "human-approval:"


# --------------------------------------------------------------------------
# Error taxonomy (all `ChatgptObserverError` subclasses, same shape as the
# rest of the package — `error_code`/`context`/`to_job_error()`).
# --------------------------------------------------------------------------
class SchedulingBoundaryError(ChatgptObserverError):
    """A registered observation cell handed to the scheduler is incomplete —
    one of `query_cluster_ref`/`locale`/`browser_policy`/`repeat_count` is
    missing/blank or `repeat_count` is not a positive int. Binding these
    fields is w5-04's job (experiment→measurement binding); the scheduler
    only validates COMPLETENESS and fails closed on a partial cell."""

    error_code = "saena.validation.observation_cell_incomplete"


class SchedulingWindowError(ChatgptObserverError):
    """The measurement window is missing, inverted (end <= start), or not
    expressed in whole epoch seconds."""

    error_code = "saena.validation.measurement_window_invalid"


class SchedulingRatePolicyError(ChatgptObserverError):
    """A `RatePolicy` field is out of range, or the requested schedule cannot
    fit inside the window at the policy's slot stride (fail closed — never
    silently over-schedules or truncates)."""

    error_code = "saena.rate_limited.schedule_exceeds_rate_policy"


class SchedulingApprovalRequiredError(ChatgptObserverError):
    """A caller asked for `provenance=production` scheduling/observation
    without a well-formed human approval token. Production external
    observation is BLOCKED(human) in Wave 5 — this is the fail-closed
    placeholder protocol, never a path this code can satisfy on its own."""

    error_code = "saena.policy_denied.production_observation_not_approved"


# --------------------------------------------------------------------------
# Value objects
# --------------------------------------------------------------------------
class Arm(enum.Enum):
    """A measurement arm. `BASELINE`/`TREATMENT`/`CONTROL` are the three arms
    a DiD-style measurement schedule balances across (wave5-plan.md E1:
    "Treatment/control registration"; baseline = the pre-treatment reference
    series)."""

    BASELINE = "baseline"
    TREATMENT = "treatment"
    CONTROL = "control"


class Provenance(enum.Enum):
    """Where a scheduled slot's observation is allowed to come from.

    `FIXTURE` is the only value this module can emit without a human approval
    token — it maps to `ApprovedFixtureObserver` replay. `PRODUCTION` is a
    fail-closed placeholder: requesting it requires a well-formed approval
    token the scheduler NEVER mints itself (BLOCKED(human), wave5-plan H2)."""

    FIXTURE = "fixture"
    PRODUCTION = "production"


@dataclass(frozen=True, slots=True)
class ObservationCell:
    """A registered observation cell as handed to the scheduler.

    Every field is bound UPSTREAM at registration/binding time (w5-04) — the
    scheduler treats this object as authoritative-but-untrusted input and only
    checks that it is COMPLETE, never fills a blank in. `domain_key` is the
    rate-limit bucket key: the per-domain rate limit and concurrent-session
    quota in `RatePolicy` apply per distinct `domain_key` (one schedule = one
    cell = one domain bucket).
    """

    query_cluster_ref: str
    locale: str
    browser_policy: str
    repeat_count: int
    domain_key: str

    def validate(self) -> None:
        """Fail closed unless every registration field is present and
        well-formed. Called by `ObservationCellSchedule.build`."""
        for field_name, value in (
            ("query_cluster_ref", self.query_cluster_ref),
            ("locale", self.locale),
            ("browser_policy", self.browser_policy),
            ("domain_key", self.domain_key),
        ):
            if not isinstance(value, str) or not value:
                raise SchedulingBoundaryError(
                    f"observation cell field {field_name!r} must be a non-empty "
                    "string (bound upstream at registration by w5-04)",
                    context={"field": field_name},
                )
        if not isinstance(self.repeat_count, int) or isinstance(self.repeat_count, bool):
            raise SchedulingBoundaryError(
                "repeat_count must be an int",
                context={"field": "repeat_count", "value": repr(self.repeat_count)},
            )
        if self.repeat_count < 1:
            raise SchedulingBoundaryError(
                f"repeat_count must be >= 1, got {self.repeat_count}",
                context={"field": "repeat_count", "value": self.repeat_count},
            )


@dataclass(frozen=True, slots=True)
class MeasurementWindow:
    """A measurement window `[start_epoch_s, end_epoch_s]`, in whole seconds
    since the epoch. No wall-clock is ever read to build this — the caller (a
    Temporal workflow in w5-14, a test here) always supplies both ends
    explicitly, keeping the schedule deterministic."""

    start_epoch_s: int
    end_epoch_s: int

    def validate(self) -> None:
        for field_name, value in (
            ("start_epoch_s", self.start_epoch_s),
            ("end_epoch_s", self.end_epoch_s),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise SchedulingWindowError(
                    f"{field_name} must be an int (whole seconds since epoch)",
                    context={"field": field_name, "value": repr(value)},
                )
        if self.end_epoch_s <= self.start_epoch_s:
            raise SchedulingWindowError(
                f"window end ({self.end_epoch_s}) must be strictly after start "
                f"({self.start_epoch_s})",
                context={"start": self.start_epoch_s, "end": self.end_epoch_s},
            )

    @property
    def duration_s(self) -> int:
        return self.end_epoch_s - self.start_epoch_s


@dataclass(frozen=True, slots=True)
class RatePolicy:
    """Frozen, mechanism-only rate/quota/backoff/imbalance policy.

    NO field has a production default — every value is caller-injected (a
    TEST-ONLY fixture in the unit lane). This model fixes the MECHANISM
    (fields + how the scheduler consumes them); the production values are a
    human decision (wave5-plan.md H2, BLOCKED(human)).

    - `max_per_day`: ROLLING per-domain rate cap — at most this many slots may
      fall in ANY half-open 24h interval `[t, t+86400)` for a single
      `domain_key`. Enforced by construction via `slot_stride_seconds` (see
      below), never by calendar-day buckets, so a sliding window straddling a
      day boundary can never exceed the cap.
    - `max_concurrent`: concurrent-session quota — slot `i` is bookkept on
      lane `i % max_concurrent`; same-lane slots start
      `max_concurrent * slot_stride_seconds` apart. PRECONDITION (documented,
      owned by the executing caller — this module schedules instants, it does
      not run observations): the "at most `max_concurrent` in flight"
      guarantee holds provided each observation's runtime is at most
      `max_concurrent * slot_stride_seconds` (a runtime of at most
      `min_gap_seconds` gives in-flight concurrency of at most 1).
    - `min_gap_seconds`: minimum spacing between ANY two consecutive slots.
    - `backoff_base_seconds` / `backoff_factor` / `backoff_cap_seconds` /
      `max_retries`: deterministic exponential backoff parameters. The
      per-slot retry stagger is `min(base * factor**(idx % (max_retries+1)),
      cap)` — a pure function of the slot index, NO random jitter.
    - `imbalance_ratio_cap`: the largest allowed ratio between the biggest and
      smallest arm's slot count. `1.0` demands perfectly equal arms. NOTE:
      today's `build()` path always produces equal arms (see module docstring
      "Arm balancing note") — this cap is the binding contract for a future
      arm-weighting path, enforced by `_guard_imbalance` as defense-in-depth.
      TEST-ONLY fixture value; a production imbalance cap is BLOCKED(human).
    """

    max_per_day: int
    max_concurrent: int
    min_gap_seconds: int
    backoff_base_seconds: int
    backoff_factor: int
    backoff_cap_seconds: int
    max_retries: int
    imbalance_ratio_cap: float

    def validate(self) -> None:
        for field_name, value in (
            ("max_per_day", self.max_per_day),
            ("max_concurrent", self.max_concurrent),
            ("min_gap_seconds", self.min_gap_seconds),
            ("backoff_base_seconds", self.backoff_base_seconds),
            ("backoff_factor", self.backoff_factor),
            ("backoff_cap_seconds", self.backoff_cap_seconds),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise SchedulingRatePolicyError(
                    f"{field_name} must be a positive int, got {value!r}",
                    context={"field": field_name, "value": repr(value)},
                )
        if not isinstance(self.max_retries, int) or isinstance(self.max_retries, bool):
            raise SchedulingRatePolicyError(
                "max_retries must be an int",
                context={"field": "max_retries", "value": repr(self.max_retries)},
            )
        if self.max_retries < 0:
            raise SchedulingRatePolicyError(
                f"max_retries must be >= 0, got {self.max_retries}",
                context={"field": "max_retries", "value": self.max_retries},
            )
        if self.backoff_cap_seconds < self.backoff_base_seconds:
            raise SchedulingRatePolicyError(
                f"backoff_cap_seconds ({self.backoff_cap_seconds}) must be >= "
                f"backoff_base_seconds ({self.backoff_base_seconds})",
                context={
                    "backoff_cap_seconds": self.backoff_cap_seconds,
                    "backoff_base_seconds": self.backoff_base_seconds,
                },
            )
        if (
            not isinstance(self.imbalance_ratio_cap, (int, float))
            or isinstance(self.imbalance_ratio_cap, bool)
            or self.imbalance_ratio_cap < 1.0
        ):
            raise SchedulingRatePolicyError(
                "imbalance_ratio_cap must be a real number >= 1.0, got "
                f"{self.imbalance_ratio_cap!r}",
                context={"imbalance_ratio_cap": repr(self.imbalance_ratio_cap)},
            )

    @property
    def slot_stride_seconds(self) -> int:
        """Uniform spacing between consecutive slot starts:
        `max(min_gap_seconds, ceil(86400 / max_per_day))`.

        The ROLLING per-day invariant follows by construction: with
        consecutive slots at least `ceil(86400 / max_per_day)` apart, any
        half-open 24h interval `[t, t+86400)` contains at most `max_per_day`
        slot starts — for every sliding anchor `t`, including anchors that
        straddle a calendar-day boundary."""
        day_stride = -(-_SECONDS_PER_DAY // self.max_per_day)  # ceil division
        return max(self.min_gap_seconds, day_stride)

    def backoff_stagger_for(self, slot_index: int) -> int:
        """Deterministic exponential backoff stagger for `slot_index`.

        `min(base * factor ** (slot_index % (max_retries + 1)), cap)`. NO
        random jitter — the modulo of the slot index is the sole source of the
        exponent, so the sequence is monotonic-then-reset and byte-identical
        across runs. When `max_retries == 0` the exponent is always 0, so the
        stagger is a constant `base` (clamped to `cap`)."""
        exponent = slot_index % (self.max_retries + 1)
        raw = self.backoff_base_seconds * (self.backoff_factor**exponent)
        return min(raw, self.backoff_cap_seconds)


@dataclass(frozen=True, slots=True)
class ObservationSlot:
    """One scheduled observation. Immutable. `scheduled_at_epoch_s` is the
    instant the slot's observation should run; `backoff_stagger_seconds` is
    the deterministic retry stagger (added on top of `scheduled_at` on a retry
    — the scheduler records it, the caller/observer applies it). `lane` is the
    concurrency-lane bookkeeping index (`0 <= lane < max_concurrent`);
    same-lane slots start `max_concurrent * slot_stride_seconds` apart — see
    `RatePolicy.max_concurrent` for the documented runtime-budget precondition
    under which the lane model bounds in-flight concurrency."""

    arm: Arm
    provenance: Provenance
    slot_index: int
    lane: int
    scheduled_at_epoch_s: int
    backoff_stagger_seconds: int
    query_cluster_ref: str
    locale: str
    browser_policy: str
    domain_key: str


# --------------------------------------------------------------------------
# Arm balancing
# --------------------------------------------------------------------------
# Round-robin arm order: BASELINE, CONTROL, TREATMENT, repeat. The build()
# total is always `repeat_count * 3` (divisible by 3), so today's arms are
# always exactly equal and `_guard_imbalance` cannot fire on the build() path
# — see the module docstring's "Arm balancing note" for the honest dead-code
# disclosure and why the guard is kept (defense-in-depth for future
# arm-weighting; unit-tested directly against synthetic uneven arm lists).
_ARM_ROTATION: tuple[Arm, ...] = (Arm.BASELINE, Arm.CONTROL, Arm.TREATMENT)


def _assign_arms(total_slots: int) -> list[Arm]:
    return [_ARM_ROTATION[i % len(_ARM_ROTATION)] for i in range(total_slots)]


def _arm_counts(arms: Sequence[Arm]) -> dict[Arm, int]:
    counts = {arm: 0 for arm in _ARM_ROTATION}
    for arm in arms:
        counts[arm] += 1
    return counts


# --------------------------------------------------------------------------
# The scheduler
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ObservationCellSchedule:
    """A deterministic, immutable schedule of `ObservationSlot`s for one
    registered observation cell across one measurement window under one
    `RatePolicy`. Build it with `ObservationCellSchedule.build(...)`."""

    cell: ObservationCell
    window: MeasurementWindow
    policy: RatePolicy
    provenance: Provenance
    slots: tuple[ObservationSlot, ...]

    @classmethod
    def build(
        cls,
        *,
        cell: ObservationCell,
        window: MeasurementWindow,
        policy: RatePolicy,
        provenance: Provenance = Provenance.FIXTURE,
        production_approval_token: str | None = None,
    ) -> ObservationCellSchedule:
        """Build the deterministic schedule, or fail closed.

        Boundary guards, in order:
          1. `provenance=PRODUCTION` requires a WELL-FORMED
             `production_approval_token`: a string of shape
             `human-approval:<non-empty>` (mechanism-only placeholder — this
             code checks the shape and fails closed; it never mints or
             verifies a token, a human issues it; Wave 5: BLOCKED(human)).
          2. the cell must be complete (`cell.validate()`).
          3. the window must be present and well-formed (`window.validate()`).
          4. the policy must be in range (`policy.validate()`).
          5. arm balance must satisfy `imbalance_ratio_cap`
             (defense-in-depth; always satisfied on today's build() path).
          6. the requested slot count (`repeat_count` per arm × 3 arms) must
             fit the window at `slot_stride_seconds` spacing — else
             `SchedulingRatePolicyError` (never silently truncated).
        """
        _guard_production_approval(provenance, production_approval_token)

        cell.validate()
        window.validate()
        policy.validate()

        total_slots = cell.repeat_count * len(_ARM_ROTATION)
        arms = _assign_arms(total_slots)
        _guard_imbalance(arms, policy)
        _guard_rate_limits(total_slots=total_slots, window=window, policy=policy)

        slots = _lay_out_slots(
            cell=cell,
            window=window,
            policy=policy,
            provenance=provenance,
            arms=arms,
        )
        return cls(
            cell=cell,
            window=window,
            policy=policy,
            provenance=provenance,
            slots=tuple(slots),
        )

    def slots_for_arm(self, arm: Arm) -> tuple[ObservationSlot, ...]:
        return tuple(slot for slot in self.slots if slot.arm is arm)

    def arm_counts(self) -> dict[Arm, int]:
        return _arm_counts([slot.arm for slot in self.slots])


def _guard_production_approval(provenance: Provenance, token: str | None) -> None:
    """Fail closed unless a PRODUCTION-provenance request presents a
    well-formed placeholder approval token (`human-approval:<non-empty>`).

    MECHANISM ONLY: shape validation, nothing more — no signature check, no
    registry lookup, no expiry. A real production approval protocol (identity,
    signing, audit) is a HUMAN/W-later decision; until then every malformed or
    absent token is a DENY."""
    if provenance is not Provenance.PRODUCTION:
        return
    if (
        not isinstance(token, str)
        or not token.startswith(APPROVAL_TOKEN_PREFIX)
        or len(token) <= len(APPROVAL_TOKEN_PREFIX)
    ):
        raise SchedulingApprovalRequiredError(
            "production-provenance scheduling requires a human approval token "
            f"of shape {APPROVAL_TOKEN_PREFIX!r}<non-empty> (Wave 5: live "
            "observation BLOCKED(human); this code never mints or verifies "
            "one — shape-check only, fail-closed)",
            context={"provenance": provenance.value},
        )


def _guard_imbalance(arms: Sequence[Arm], policy: RatePolicy) -> None:
    counts = _arm_counts(arms)
    populated = [c for c in counts.values() if c > 0]
    if not populated:
        return
    lo = min(populated)
    hi = max(populated)
    # lo is always >= 1 here (round-robin fills BASELINE first), so this ratio
    # is well-defined.
    ratio = hi / lo
    if ratio > policy.imbalance_ratio_cap:
        raise SchedulingRatePolicyError(
            f"arm imbalance ratio {ratio:.4f} exceeds policy cap "
            f"{policy.imbalance_ratio_cap:.4f} (counts={{'baseline': "
            f"{counts[Arm.BASELINE]}, 'control': {counts[Arm.CONTROL]}, "
            f"'treatment': {counts[Arm.TREATMENT]}}})",
            context={
                "imbalance_ratio": ratio,
                "imbalance_ratio_cap": policy.imbalance_ratio_cap,
                "baseline": counts[Arm.BASELINE],
                "control": counts[Arm.CONTROL],
                "treatment": counts[Arm.TREATMENT],
            },
        )


def _guard_rate_limits(*, total_slots: int, window: MeasurementWindow, policy: RatePolicy) -> None:
    """Fail closed unless `total_slots` uniformly-strided slots fit inside the
    window. With `stride = policy.slot_stride_seconds` the last slot starts at
    `start + (total_slots - 1) * stride`, which must be `<= end`. The rolling
    per-day cap and the min-gap are already embedded in the stride itself
    (see `RatePolicy.slot_stride_seconds`), so fitting the window is the only
    remaining capacity condition — and over-subscription is a hard error,
    never a silent truncation."""
    stride = policy.slot_stride_seconds
    capacity = window.duration_s // stride + 1
    if total_slots > capacity:
        raise SchedulingRatePolicyError(
            f"requested {total_slots} slots exceed schedulable capacity "
            f"{capacity} for this window under the rate policy "
            f"(slot_stride_seconds={stride} = max(min_gap_seconds="
            f"{policy.min_gap_seconds}, ceil(86400/max_per_day="
            f"{policy.max_per_day})), window_duration_s={window.duration_s})",
            context={
                "total_slots": total_slots,
                "capacity": capacity,
                "slot_stride_seconds": stride,
                "min_gap_seconds": policy.min_gap_seconds,
                "max_per_day": policy.max_per_day,
                "window_duration_s": window.duration_s,
            },
        )


def _lay_out_slots(
    *,
    cell: ObservationCell,
    window: MeasurementWindow,
    policy: RatePolicy,
    provenance: Provenance,
    arms: Sequence[Arm],
) -> list[ObservationSlot]:
    """Place slot `i` at `window.start + i * slot_stride_seconds`, on lane
    `i % max_concurrent`.

    Deterministic and uniformly spaced: consecutive slots are exactly one
    stride apart, so (a) any half-open 24h interval holds at most
    `max_per_day` slots (stride >= ceil(86400/max_per_day) — the ROLLING day
    cap, valid for every sliding anchor), (b) any two consecutive slots are at
    least `min_gap_seconds` apart (stride >= min_gap_seconds), and (c)
    same-lane slots are `max_concurrent * stride` apart (the lane model's
    concurrency bookkeeping — see `RatePolicy.max_concurrent` for the
    documented runtime precondition). The rate-limit guard has already proven
    every slot fits before `window.end`.
    """
    stride = policy.slot_stride_seconds
    slots: list[ObservationSlot] = []
    for i, arm in enumerate(arms):
        slots.append(
            ObservationSlot(
                arm=arm,
                provenance=provenance,
                slot_index=i,
                lane=i % policy.max_concurrent,
                scheduled_at_epoch_s=window.start_epoch_s + i * stride,
                backoff_stagger_seconds=policy.backoff_stagger_for(i),
                query_cluster_ref=cell.query_cluster_ref,
                locale=cell.locale,
                browser_policy=cell.browser_policy,
                domain_key=cell.domain_key,
            )
        )
    return slots


# --------------------------------------------------------------------------
# Approved-fixture observer adapter
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class FixtureObservation:
    """One approved fixture observation replayed for a scheduled slot. Carries
    only opaque refs + provenance — never raw content, never a live-fetched
    payload. `provenance` is ALWAYS `Provenance.FIXTURE` (stamped by
    `ApprovedFixtureObserver`, not caller-settable)."""

    slot_index: int
    arm: Arm
    query_cluster_ref: str
    locale: str
    citation_refs: tuple[str, ...]
    raw_object_ref: str
    provenance: Provenance


class ApprovedFixtureObserver:
    """The service's observation port, implemented for tests by REPLAYING
    approved fixture observations deterministically.

    Structurally cannot reach the network: this class (and its whole module)
    pulls in no network/browser/socket library — enforced by the unit lane's
    source-level import scan (see module docstring for that guard's honest
    scope) — and exposes exactly one read verb (`observe_slot`) that looks its
    answer up in an in-memory, caller-registered fixture table; there is no
    fetch/navigate/login/submit method anywhere on it (same read-only
    discipline as `source.ObservationSourcePort` / `pool.BrowserSessionPort`).
    Every observation it returns is stamped `provenance=fixture`; it refuses —
    per slot AND per schedule — to serve `provenance=production` (that is a
    BLOCKED(human) path, and this adapter is the fixture side of it by
    construction).

    Register canned observations keyed by `(query_cluster_ref, locale)` via
    `register`; `observe_slot(slot)` replays the matching fixture for a
    scheduled `ObservationSlot`. Replay is stable: the same slot returns the
    same `FixtureObservation` every call.
    """

    def __init__(self) -> None:
        self._fixtures: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {}
        self.observe_calls: list[int] = []

    def register(
        self,
        *,
        query_cluster_ref: str,
        locale: str,
        citation_refs: Sequence[str],
        raw_object_ref: str,
    ) -> None:
        """Register an approved fixture observation for a
        `(query_cluster_ref, locale)` key."""
        self._fixtures[(query_cluster_ref, locale)] = (
            tuple(citation_refs),
            raw_object_ref,
        )

    def observe_slot(self, slot: ObservationSlot) -> FixtureObservation:
        """Replay the approved fixture observation for `slot`. Fail closed
        (`SchedulingApprovalRequiredError`) on any non-fixture-provenance slot
        — symmetric with `replay_schedule`'s whole-schedule guard. Fail closed
        (`SchedulingBoundaryError`) if the slot's cell has no registered
        fixture — a test-harness misconfiguration, never a silent live-fetch
        fallback. Records the call."""
        if slot.provenance is not Provenance.FIXTURE:
            raise SchedulingApprovalRequiredError(
                "ApprovedFixtureObserver only serves fixture-provenance slots, "
                f"got {slot.provenance.value!r} (slot_index={slot.slot_index})",
                context={
                    "provenance": slot.provenance.value,
                    "slot_index": slot.slot_index,
                },
            )
        self.observe_calls.append(slot.slot_index)
        key = (slot.query_cluster_ref, slot.locale)
        fixture = self._fixtures.get(key)
        if fixture is None:
            raise SchedulingBoundaryError(
                "no approved fixture registered for "
                f"(query_cluster_ref={slot.query_cluster_ref!r}, "
                f"locale={slot.locale!r}) — the fixture observer never "
                "falls back to a live fetch",
                context={
                    "query_cluster_ref": slot.query_cluster_ref,
                    "locale": slot.locale,
                },
            )
        citation_refs, raw_object_ref = fixture
        return FixtureObservation(
            slot_index=slot.slot_index,
            arm=slot.arm,
            query_cluster_ref=slot.query_cluster_ref,
            locale=slot.locale,
            citation_refs=citation_refs,
            raw_object_ref=raw_object_ref,
            provenance=Provenance.FIXTURE,
        )

    def replay_schedule(self, schedule: ObservationCellSchedule) -> tuple[FixtureObservation, ...]:
        """Replay every slot in `schedule` in order. Requires the schedule's
        provenance be `FIXTURE` (fail closed otherwise — this adapter is the
        fixture side and never serves a production-provenance schedule; the
        per-slot guard in `observe_slot` backstops this at slot granularity
        too)."""
        if schedule.provenance is not Provenance.FIXTURE:
            raise SchedulingApprovalRequiredError(
                "ApprovedFixtureObserver only replays fixture-provenance "
                f"schedules, got {schedule.provenance.value!r}",
                context={"provenance": schedule.provenance.value},
            )
        return tuple(self.observe_slot(slot) for slot in schedule.slots)


# Denylist consulted by the unit lane's no-network guard: a DIRECT
# source-level scan of this module (and its first-party
# `saena_chatgpt_observer.errors` dependency) asserting none of these appears
# in an import statement. Honest scope: a mechanical text scan of import
# statements, NOT a transitive third-party import-graph analysis (see module
# docstring).
FORBIDDEN_IMPORT_PREFIXES: tuple[str, ...] = (
    "aiohttp",
    "ftplib",
    "http.client",
    "httpx",
    "playwright",
    "requests",
    "selenium",
    "socket",
    "urllib",
    "urllib3",
    "websockets",
)

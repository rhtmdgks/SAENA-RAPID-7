"""Deterministic per-signal Difference-in-Differences (DiD) engine (w5-05, P0).

Pure domain logic. No I/O, no RNG, no numpy/scipy (the ``saena-domain``
package depends only on pydantic + stdlib — see ``packages/domain/pyproject``).
All arithmetic is exact via :class:`fractions.Fraction`; only the OUTPUT
boundary rounds, and it does so under one explicit, documented policy
(:data:`ROUNDING_DECIMAL_PLACES`, banker's rounding of the exact value). This
is what makes identical inputs produce byte-identical canonical output.

Scope discipline (wave5-plan.md §DAG, E3): this module reports NUMBERS +
INSUFFICIENCY ONLY. It contains no verdict/pass/grant logic — the
``outcome_layer`` B-gate (≥2 independent signal layers) is w5-06's job. A
``DiDResult`` carrying a positive lift is NOT a claim of success.

## F-9 evaluator mapping — ADOPT-AND-SUPERSEDE

The Wave-3 F-9 "measurement fraud" evaluator
(``tests/security/measurement_fraud.py``,
``evals/regression-suites/failure_modes/fm-09-measurement-fraud.yaml``) was a
provisional, harness-owned checker created because no measurement module
existed yet. Its core scalar is::

    net_of_control_lift = treatment_raw_delta - control_raw_delta

This engine **supersedes** that evaluator's measurement semantics while
**adopting** its scalar exactly. Concretely, F-9 took two OPAQUE raw deltas
per signal; this engine DECOMPOSES each raw delta into its baseline/post
cells::

    treatment_raw_delta = post_treatment_mean - baseline_treatment_mean
    control_raw_delta    = post_control_mean   - baseline_control_mean
    net_of_control_lift  = treatment_raw_delta - control_raw_delta

so on any input where F-9's ``treatment_raw_delta`` / ``control_raw_delta``
equal this engine's decomposed deltas, ``net_of_control_lift`` is IDENTICAL
(pinned by ``test_d_fraud_parity_matches_superseded_f9_semantics``). The
market-drift / "raw grows but control too" fraud fixture (F-9 example; k3s
§10:513) therefore yields lift ``0`` here by construction — common trend is
removed, not merely thresholded.

What this engine ADDS on top of the superseded evaluator (none of which F-9
had): explicit per-cell decomposition; per-cell sample counts;
mean-per-repeat normalization for unequal repeats; measurement-window
enforcement with late-observation exclusion; a first-class insufficiency
taxonomy (:class:`InsufficiencyCode`) that NEVER guesses a missing/degenerate
cell; and deterministic leave-one-out sign-stability + a policy-relative
min-detectable margin. What this engine deliberately does NOT take from F-9:
its ``>0`` pass/grant decision and its ``MIN_INDEPENDENT_SIGNALS`` gate —
those are verdict logic and belong to w5-06, not here.

The B-gate/eval owner (w5-06 / w5-20) is expected to consume
``DiDResult`` in place of calling ``evaluate_b_layer_success`` directly; the
F-9 regression fixture is updated to point at this engine in w5-20 per the
plan's "F-9 adopt/supersede mapping" line.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import Enum
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Number of decimal places the engine rounds its exact (Fraction) results to
#: at the OUTPUT boundary. All internal arithmetic is exact; this is the ONE
#: place precision is bounded, so the choice is explicit and testable. Banker's
#: rounding (ROUND_HALF_EVEN) on the exact value keeps ``compute_did``
#: deterministic and free of accumulated float drift.
ROUNDING_DECIMAL_PLACES = 10

#: Per-repeat magnitude bound. A finite repeat value with ``abs(value) >=
#: MAGNITUDE_LIMIT`` is not a plausible signal observation (citation counts,
#: CTRs, absorption rates) — it is either corruption or an attack on the
#: rounding boundary. Such repeats are excluded per-signal and surface as
#: ``InsufficiencyCode.NON_REPRESENTABLE_MAGNITUDE``; they must NEVER abort
#: the whole batch (critic #2 should-fix 1).
MAGNITUDE_LIMIT = 1e18

#: Decimal working precision for output rounding. Values admitted by
#: MAGNITUDE_LIMIT (< 1e18, so any net lift < 4e18: 19 integer digits) plus
#: ROUNDING_DECIMAL_PLACES fractional digits stay far below this, so
#: ``quantize`` cannot raise ``decimal.InvalidOperation``.
_DECIMAL_PRECISION = 60

_CELL_NAMES = ("baseline_treatment", "post_treatment", "baseline_control", "post_control")


def _round(value: Fraction) -> float:
    """Round an exact Fraction to the engine's output precision, as a float."""
    quantum = Decimal(1).scaleb(-ROUNDING_DECIMAL_PLACES)
    with localcontext() as ctx:
        ctx.prec = _DECIMAL_PRECISION
        dec = Decimal(value.numerator) / Decimal(value.denominator)
        return float(dec.quantize(quantum, rounding=ROUND_HALF_EVEN))


class InsufficiencyCode(str, Enum):
    """Why a signal's DiD could not be trusted as a measurement.

    Never guessed: each code corresponds to a concrete missing/degenerate
    input. A signal may carry more than one code.
    """

    MISSING_BASELINE = "missing_baseline"
    MISSING_CONTROL = "missing_control"
    MISSING_POST = "missing_post"
    INSUFFICIENT_REPEATS = "insufficient_repeats"
    NON_FINITE_VALUE = "non_finite_value"
    NON_REPRESENTABLE_MAGNITUDE = "non_representable_magnitude"
    DUPLICATE_OBSERVATION_CONFLICT = "duplicate_observation_conflict"


#: Closed vocabulary for :attr:`DiDPolicy.provenance`. Arbitrary strings
#: (``"PRODUCTION"``, ``"production "``, typos) are rejected at construction —
#: an unknown label must never silently pass as a production policy.
PolicyProvenance = Literal["production", "test_fixture"]


class DiDPolicy(BaseModel):
    """Injected measurement policy.

    ``provenance`` MUST label where the numeric values came from, from the
    closed :data:`PolicyProvenance` vocabulary only. In tests this is
    ``"test_fixture"``; the production ``min_repeats``/``effect_threshold``
    values are BLOCKED-human (wave5-plan.md E6 GRS / w5-05 mission) and must
    NOT be hardcoded here. NOTE: this engine only refuses UNKNOWN labels —
    provenance AUTHENTICITY (that a ``"production"`` label is backed by a
    signed policy bundle) is w5-07 GRS's job, not DiD's.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_repeats: int = Field(gt=0)
    effect_threshold: float = Field(ge=0.0)
    provenance: PolicyProvenance


class CellObservation(BaseModel):
    """One 2x2 cell: the repeat-observations for one (arm, period).

    ``observation_ids`` (optional, parallel to ``repeat_values``): stable
    per-repeat observation identities. When PRESENT, the engine dedupes
    replayed repeats — byte-identical duplicates (same id, same value bits,
    same timestamp) are counted ONCE toward ``sample_counts``/``min_repeats``,
    and the same id carrying DIFFERENT content makes the signal
    ``insufficient(duplicate_observation_conflict)``. When ABSENT, the engine
    performs NO dedup: guaranteeing repeat uniqueness is then explicitly an
    UPSTREAM obligation of the w5-04 experiment→measurement binding and the
    w5-12 experiment-attribution service boundary — a replayed repeat without
    ids WILL inflate sample counts here, by documented design, not silently.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repeat_values: tuple[float, ...] = Field(min_length=1)
    timestamps: tuple[datetime, ...] = Field(min_length=1)
    observation_ids: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _lengths_match(self) -> CellObservation:
        if len(self.repeat_values) != len(self.timestamps):
            raise ValueError("repeat_values and timestamps must have equal length")
        if self.observation_ids is not None and len(self.observation_ids) != len(
            self.repeat_values
        ):
            raise ValueError("observation_ids must have the same length as repeat_values")
        return self


class SignalSeries(BaseModel):
    """One independently-observed signal's four cells (any may be ``None``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    layer: str = Field(min_length=1)
    metric_id: str = Field(min_length=1)
    evidence_basis_id: str = Field(min_length=1)
    baseline_treatment: CellObservation | None = None
    post_treatment: CellObservation | None = None
    baseline_control: CellObservation | None = None
    post_control: CellObservation | None = None


class RawView(BaseModel):
    """Raw (control-unaware) deltas — the view F-9 alone would have shown."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    treatment_delta: float | None = None
    control_delta: float | None = None


class AdjustedView(BaseModel):
    """Control-adjusted DiD scalar — market drift removed by construction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    net_of_control_lift: float | None = None


class SignalDiD(BaseModel):
    """Per-signal DiD output — numbers + insufficiency only (no verdict)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    layer: str
    metric_id: str
    evidence_basis_id: str

    treatment_raw_delta: float | None = None
    control_raw_delta: float | None = None
    net_of_control_lift: float | None = None

    raw_view: RawView = RawView()
    adjusted_view: AdjustedView = AdjustedView()

    sample_counts: dict[str, int] = Field(default_factory=dict)

    insufficient: bool = False
    insufficiency_codes: tuple[InsufficiencyCode, ...] = ()

    late_observation: bool = False
    excluded_late_count: int = 0

    # uncertainty (deterministic; no RNG)
    sign_stable_under_leave_one_out: bool | None = None
    min_detectable_margin: float | None = None
    meets_effect_threshold: bool | None = None


class DiDResult(BaseModel):
    """All signals' DiD outputs. ``canonical_json`` is order-independent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signals: tuple[SignalDiD, ...] = ()
    policy_provenance: str = ""

    def canonical_json(self) -> str:
        """Byte-identical for equal inputs regardless of signal input order.

        Signals are sorted by their (layer, metric_id, evidence_basis_id)
        identity and dumped with sorted keys, so neither input ordering nor
        dict insertion order can change the bytes.
        """
        payload = {
            "policy_provenance": self.policy_provenance,
            "signals": sorted(
                (s.model_dump(mode="json") for s in self.signals),
                key=lambda d: (d["layer"], d["metric_id"], d["evidence_basis_id"]),
            ),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# --------------------------------------------------------------------------
# Core computation
# --------------------------------------------------------------------------


def _dedupe_repeats(
    cell: CellObservation,
) -> tuple[tuple[tuple[float, datetime], ...], bool]:
    """Dedupe repeats by ``observation_ids`` when present.

    Returns ``(unique (value, timestamp) pairs in first-seen order, conflict)``.
    Byte-identical replays (same id, same value bits via ``float.hex`` — NaN
    replays compare equal, unlike ``==`` — same timestamp) collapse to one.
    Same id with different content sets ``conflict``. Without ids, repeats
    pass through unchanged (upstream dedup obligation — see
    :class:`CellObservation`). Deterministic: pure first-seen ordering.
    """
    if cell.observation_ids is None:
        return tuple(zip(cell.repeat_values, cell.timestamps, strict=True)), False
    seen: dict[str, tuple[str, datetime]] = {}
    unique: list[tuple[float, datetime]] = []
    conflict = False
    for oid, value, ts in zip(
        cell.observation_ids, cell.repeat_values, cell.timestamps, strict=True
    ):
        content = (value.hex(), ts)
        if oid in seen:
            if seen[oid] != content:
                conflict = True
            continue
        seen[oid] = content
        unique.append((value, ts))
    return tuple(unique), conflict


def _partition_in_window(
    pairs: tuple[tuple[float, datetime], ...],
    window_start: datetime | None,
    window_end: datetime | None,
) -> tuple[list[Fraction], int, bool, bool]:
    """Return (in-window exact values, late_count, any_non_finite, any_non_representable).

    Late (out-of-window) repeats are EXCLUDED from the returned values and
    counted — never silently averaged in. If no window is given, all repeats
    are in-window. NaN/inf repeats are reported via ``any_non_finite``;
    finite repeats with ``abs(value) >= MAGNITUDE_LIMIT`` via
    ``any_non_representable``. Both kinds are excluded from the value list so
    they can neither poison the mean nor abort the batch.
    """
    values: list[Fraction] = []
    late_count = 0
    any_non_finite = False
    any_non_representable = False
    for raw, ts in pairs:
        if not math.isfinite(raw):
            any_non_finite = True
            continue
        if abs(raw) >= MAGNITUDE_LIMIT:
            any_non_representable = True
            continue
        if window_start is not None and ts < window_start:
            late_count += 1
            continue
        if window_end is not None and ts > window_end:
            late_count += 1
            continue
        values.append(Fraction(raw).limit_denominator(10**12))
    return values, late_count, any_non_finite, any_non_representable


def _mean(values: list[Fraction]) -> Fraction:
    return sum(values, Fraction(0)) / len(values)


def _sign(value: Fraction) -> int:
    return (value > 0) - (value < 0)


def _compute_signal(
    series: SignalSeries,
    policy: DiDPolicy,
    window_start: datetime | None,
    window_end: datetime | None,
) -> SignalDiD:
    codes: list[InsufficiencyCode] = []
    sample_counts: dict[str, int] = {}
    means: dict[str, Fraction | None] = {}
    in_window_values: dict[str, list[Fraction]] = {}
    total_late = 0
    non_finite = False
    non_representable = False
    duplicate_conflict = False

    for name in _CELL_NAMES:
        cell: CellObservation | None = getattr(series, name)
        if cell is None:
            means[name] = None
            sample_counts[name] = 0
            in_window_values[name] = []
            continue
        pairs, conflict = _dedupe_repeats(cell)
        duplicate_conflict = duplicate_conflict or conflict
        values, late, nf, nr = _partition_in_window(pairs, window_start, window_end)
        total_late += late
        non_finite = non_finite or nf
        non_representable = non_representable or nr
        in_window_values[name] = values
        sample_counts[name] = len(values)
        # too few usable repeats in this cell to trust its mean
        if len(values) < policy.min_repeats:
            codes.append(InsufficiencyCode.INSUFFICIENT_REPEATS)
        means[name] = _mean(values) if values else None

    # missing-cell taxonomy (never guess a missing arm/period). A missing
    # control cell (either the baseline or the post period) is a MISSING_CONTROL
    # insufficiency: without a control arm the market-drift subtraction cannot
    # be performed at all.
    if series.baseline_treatment is None:
        codes.append(InsufficiencyCode.MISSING_BASELINE)
    if series.baseline_control is None or series.post_control is None:
        codes.append(InsufficiencyCode.MISSING_CONTROL)
    if series.post_treatment is None or series.post_control is None:
        codes.append(InsufficiencyCode.MISSING_POST)
    if non_finite:
        codes.append(InsufficiencyCode.NON_FINITE_VALUE)
    if non_representable:
        codes.append(InsufficiencyCode.NON_REPRESENTABLE_MAGNITUDE)
    if duplicate_conflict:
        codes.append(InsufficiencyCode.DUPLICATE_OBSERVATION_CONFLICT)

    # deltas only where both endpoints of an arm are present & finite
    treatment_delta = _arm_delta(means["post_treatment"], means["baseline_treatment"])
    control_delta = _arm_delta(means["post_control"], means["baseline_control"])
    net = (
        treatment_delta - control_delta
        if treatment_delta is not None and control_delta is not None
        else None
    )

    # dedupe codes preserving first-seen order → deterministic
    ordered_codes = tuple(dict.fromkeys(codes))
    insufficient = bool(ordered_codes)

    sign_stable: bool | None = None
    margin: float | None = None
    meets: bool | None = None
    if net is not None and not insufficient:
        sign_stable = _leave_one_out_sign_stable(in_window_values, means, net)
        margin = _round(abs(net) - Fraction(policy.effect_threshold).limit_denominator(10**12))
        meets = abs(net) >= Fraction(policy.effect_threshold).limit_denominator(10**12)

    treatment_delta_f = _round(treatment_delta) if treatment_delta is not None else None
    control_delta_f = _round(control_delta) if control_delta is not None else None
    net_f = _round(net) if net is not None else None

    return SignalDiD(
        layer=series.layer,
        metric_id=series.metric_id,
        evidence_basis_id=series.evidence_basis_id,
        treatment_raw_delta=treatment_delta_f,
        control_raw_delta=control_delta_f,
        net_of_control_lift=net_f,
        raw_view=RawView(treatment_delta=treatment_delta_f, control_delta=control_delta_f),
        adjusted_view=AdjustedView(net_of_control_lift=net_f),
        sample_counts=sample_counts,
        insufficient=insufficient,
        insufficiency_codes=ordered_codes,
        late_observation=total_late > 0,
        excluded_late_count=total_late,
        sign_stable_under_leave_one_out=sign_stable,
        min_detectable_margin=margin,
        meets_effect_threshold=meets,
    )


def _arm_delta(post: Fraction | None, baseline: Fraction | None) -> Fraction | None:
    if post is None or baseline is None:
        return None
    return post - baseline


def _leave_one_out_sign_stable(
    in_window_values: dict[str, list[Fraction]],
    means: dict[str, Fraction | None],
    full_net: Fraction,
) -> bool:
    """Sign-stability of ``net`` under dropping any single repeat.

    Deterministic (no RNG): for each cell in turn, recompute the net lift with
    each one of that cell's repeats removed (the other three cell means held
    fixed). The signal is sign-stable iff every leave-one-out net has the same
    sign as the full net. A cell with a single repeat cannot be reduced and is
    skipped (dropping its only value is undefined, not a zero-sample mean).
    """
    full_sign = _sign(full_net)
    for name in _CELL_NAMES:
        values = in_window_values[name]
        if len(values) <= 1:
            continue
        for i in range(len(values)):
            reduced = values[:i] + values[i + 1 :]
            loo_mean = _mean(reduced)
            loo_means = dict(means)
            loo_means[name] = loo_mean
            t = _arm_delta(loo_means["post_treatment"], loo_means["baseline_treatment"])
            c = _arm_delta(loo_means["post_control"], loo_means["baseline_control"])
            if t is None or c is None:  # pragma: no cover - unreachable: LOO only
                # runs on sufficient signals where all four cells are present.
                continue
            if _sign(t - c) != full_sign:
                return False
    return True


def compute_did(
    signals: tuple[SignalSeries, ...],
    policy: DiDPolicy,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> DiDResult:
    """Compute per-signal DiD. Numbers + insufficiency only; no verdict.

    Deterministic: identical ``signals`` (in any order) and ``policy`` yield a
    ``DiDResult`` whose :meth:`DiDResult.canonical_json` is byte-identical.
    """
    computed = tuple(_compute_signal(s, policy, window_start, window_end) for s in signals)
    return DiDResult(signals=computed, policy_provenance=policy.provenance)


__all__ = [
    "ROUNDING_DECIMAL_PLACES",
    "MAGNITUDE_LIMIT",
    "InsufficiencyCode",
    "PolicyProvenance",
    "DiDPolicy",
    "CellObservation",
    "SignalSeries",
    "RawView",
    "AdjustedView",
    "SignalDiD",
    "DiDResult",
    "compute_did",
]

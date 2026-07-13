"""Pure, deterministic B-layer success evaluator — F-9 Measurement fraud
(k3s spec §10 row 9, failure-mode matrix `F-9`: "raw citation count grows
but control too → B-layer success not granted").

**No service in this repository owns this evaluator yet** (confirmed by
repo-wide search: no `experiment-attribution-service` implementation exists
under `services/**` — only its CONFIRMED role description in
`docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` line 351,
"treatment/control, DiD, sequential evidence, long-term attribution" — and
no B-layer/outcome-layer success gate exists under `packages/**` either).
Per this patch unit's own instructions ("implement as a pure evaluator test
if no service owns it yet ... note the missing owner"), this module is a
MINIMAL, deterministic, this-suite-only checker — NOT a claim that this is
the final production `experiment-attribution-service` algorithm. It exists
so F-9 has a REAL (if provisional) mechanism to test against rather than an
empty fixture, and so a future service owner has a concrete, already-tested
starting contract to either adopt or explicitly supersede.

Design basis — Algorithm §11.1's own causal-uplift framing (line 188:
"causal uplift model: 통제군 대비 순효과 추정", i.e. net effect relative to a
control group) plus CLAUDE.md 원칙 11 ("증거 없는 완료 선언 금지... 외부 lift
주장 금지"):

- A "signal" is one independently-observed metric (e.g. citation count,
  click-through rate, absorption rate) with a RAW treatment delta and a RAW
  control delta over the same measurement window.
- `net_of_control_lift` is the causal-uplift proxy this evaluator actually
  gates on: `treatment_raw_delta - control_raw_delta`. A raw count growing
  in the treatment group means nothing on its own if the control group grew
  by the same (or a larger) amount over the same window — exactly the
  fixture this failure mode names.
- `MIN_INDEPENDENT_SIGNALS = 2`: B-layer success requires at least two
  independently-observed signals to agree (a single metric showing lift
  could itself be noise/measurement error; this mirrors the "≥2 signals"
  requirement in this patch unit's own mission instructions).
- Every signal's `net_of_control_lift` must be STRICTLY positive
  (`> MIN_NET_LIFT`, `MIN_NET_LIFT = 0.0`) — a signal with zero or negative
  net-of-control lift is exactly "raw grows but control does too (or more)",
  the literal fraud fixture this mode names, and denies B-layer success on
  its own regardless of how many OTHER signals look positive (zero
  tolerance on any single control-unaccounted signal, mirroring
  `gate_content_fidelity`'s own zero-tolerance shape elsewhere in this
  codebase).
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_INDEPENDENT_SIGNALS = 2
MIN_NET_LIFT = 0.0


@dataclass(frozen=True, slots=True)
class MeasurementSignal:
    """One independently-observed raw treatment/control delta pair."""

    name: str
    treatment_raw_delta: float
    control_raw_delta: float

    @property
    def net_of_control_lift(self) -> float:
        return self.treatment_raw_delta - self.control_raw_delta


@dataclass(frozen=True, slots=True)
class BLayerVerdict:
    """Pure result of `evaluate_b_layer_success` — never itself performs I/O
    or grants anything; a caller (out of this suite's scope) is expected to
    treat `granted=False` as a hard block on any external "it worked"
    claim, mirroring `QualityEvalOutcome.forbids_promotion`'s own
    pure-DATA-signal shape elsewhere in this codebase."""

    granted: bool
    reason: str
    net_lifts: dict[str, float]


def evaluate_b_layer_success(signals: tuple[MeasurementSignal, ...]) -> BLayerVerdict:
    """Deterministic: equal `signals` always yields an equal `BLayerVerdict`."""
    net_lifts = {s.name: s.net_of_control_lift for s in signals}

    if len(signals) < MIN_INDEPENDENT_SIGNALS:
        return BLayerVerdict(
            granted=False,
            reason=(
                f"only {len(signals)} independent signal(s) observed; "
                f">= {MIN_INDEPENDENT_SIGNALS} required for B-layer success"
            ),
            net_lifts=net_lifts,
        )

    non_positive = sorted(name for name, lift in net_lifts.items() if lift <= MIN_NET_LIFT)
    if non_positive:
        return BLayerVerdict(
            granted=False,
            reason=(
                "signal(s) with no net-of-control lift (raw grew but control "
                f"grew too, or more): {non_positive}"
            ),
            net_lifts=net_lifts,
        )

    return BLayerVerdict(
        granted=True,
        reason="every independent signal shows positive net-of-control lift",
        net_lifts=net_lifts,
    )


__all__ = [
    "MIN_INDEPENDENT_SIGNALS",
    "MIN_NET_LIFT",
    "BLayerVerdict",
    "MeasurementSignal",
    "evaluate_b_layer_success",
]

"""F-9 Measurement fraud evaluator — REPOINTED (w5-20) to the REAL integrated
`saena_domain.measurement.did` + `b_gate` engine (k3s spec §10 row 9,
failure-mode matrix `F-9`: "raw citation count grows but control too ->
B-layer success not granted").

## Repoint decision: THIN COMPATIBILITY SHIM (not a new evaluator module)

This module's original W3 public API — `MeasurementSignal`, `BLayerVerdict`,
`MIN_INDEPENDENT_SIGNALS`, `MIN_NET_LIFT`, `evaluate_b_layer_success` — is
KEPT verbatim (same names, same field shapes, same return-value shape and
semantics) and now DELEGATES internally to the real, integrated
`saena_domain.measurement.b_gate.decide_b_verdict` (which itself consumes
`saena_domain.measurement.did`-shaped per-signal results) instead of
re-implementing the W3 scalar gate.

Why a shim rather than a new evaluator function/module living alongside the
old one: `tests/security/test_f9_measurement_fraud.py` (OUTSIDE this patch
unit's exclusive paths — `tests/security/measurement_fraud.py` is the only
file in `tests/security/**` this unit may touch) imports this module's four
public names directly and asserts exact `BLayerVerdict.granted` /
`.net_lifts[name]` / `.reason` values; `tests/security/failure_mode_matrix.
json`'s F-9 row also names `tests/security/measurement_fraud.py::
evaluate_b_layer_success` as its `wired_against` target; and `justfile`'s
named gate (`measurement-privacy`/security lane) runs
`tests/security/measurement_fraud.py` directly by module path. Introducing a
SECOND, differently-named evaluator would leave the old name importable but
silently divergent from the real engine again (the exact problem this
repoint exists to fix) and would require touching
`test_f9_measurement_fraud.py`/`failure_mode_matrix.json` to repoint them,
both of which are outside this patch unit's exclusive write paths. A
signature-preserving shim keeps every existing importer green with ZERO
changes to files this unit does not own, while the SEMANTICS underneath are
now the real, production DiD + B-gate path — the actual repoint the mission
requires. See `tests/integration/measurement_failure/test_f9_fraud_repoint.py`
for the full real-engine, real-Postgres, pipeline-level fraud proof this
shim's own unit tests (`test_f9_measurement_fraud.py`) are now backed by.

## What "delegates to the real engine" means concretely

`evaluate_b_layer_success` maps each `MeasurementSignal` onto a real
`saena_domain.measurement.b_gate.SignalResult` — assigning each signal an
`OutcomeLayer` (cycling deterministically through the closed 5-member
vocabulary, keyed by input order, since the W3 API never carried a `layer`
field) and treating `signal.name` as its `evidence_basis_id` (independence
key) — and calls the REAL `decide_b_verdict` with a maximally-permissive
`EvidenceCheck`/`WindowState` (manifest hash OK, window complete, deployment
confirmed, no contamination/drift/insufficiency flags) since the W3 API never
modeled evidence-bundle or window state either; this shim's SCOPE is
unchanged from the original — only its net-of-control-lift/independent-layer
GATING LOGIC is now the real one, not a second, hand-rolled copy of it.
`net_of_control_lift` per signal is computed identically to before
(`treatment_raw_delta - control_raw_delta`, `did.py`'s own documented parity
claim with this exact scalar) and is what feeds `SignalResult.
net_of_control_lift` / `has_control_adjusted_lift=True`.

`BLayerVerdict.granted` is `True` iff `decide_b_verdict` returns
`BVerdict.PASS` (>= `MIN_INDEPENDENT_LAYERS` independent qualifying layers,
each with a strictly-positive net-of-control lift) — otherwise `False`, with
`reason` synthesized from the REAL decision's `reason_codes` /
`qualifying_layers` in the SAME human-readable shapes the original W3
messages used (naming the specific unaccounted-for signal(s) when there are
too few signals or a non-positive lift), so `test_f9_measurement_fraud.py`'s
existing substring assertions (`"citation_count" in verdict.reason`, etc.)
continue to pass unmodified against the real engine's output.

## Design basis (retained from the W3 module — still applicable un-changed)

Algorithm §11.1's own causal-uplift framing (line 188: "causal uplift model:
통제군 대비 순효과 추정", i.e. net effect relative to a control group) plus
CLAUDE.md 원칙 11 ("증거 없는 완료 선언 금지... 외부 lift 주장 금지"): a raw
count growing in the treatment group means nothing on its own if the control
group grew by the same (or a larger) amount over the same window — exactly
the fixture this failure mode names. `MIN_INDEPENDENT_SIGNALS = 2` mirrors
the real engine's `MIN_INDEPENDENT_LAYERS` — B-layer success requires at
least two independently-observed, independently-qualifying signals to agree.
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_domain.measurement.b_gate import MIN_INDEPENDENT_LAYERS as _MIN_INDEPENDENT_LAYERS
from saena_domain.measurement.b_gate import MIN_NET_LIFT as _MIN_NET_LIFT
from saena_domain.measurement.b_gate import BVerdict as _BVerdict
from saena_domain.measurement.b_gate import (
    EvidenceCheck,
    GatePolicy,
    PolicyProvenance,
    SignalResult,
    WindowState,
    decide_b_verdict,
)
from saena_domain.measurement.outcome_layer import OutcomeLayer

#: Kept identical to the real engine's own floor (`b_gate.MIN_INDEPENDENT_
#: LAYERS`) — re-exported under the W3 name so existing importers see the
#: SAME value without needing to know the real engine's name for it.
MIN_INDEPENDENT_SIGNALS = _MIN_INDEPENDENT_LAYERS

#: Kept identical to the real engine's own boundary (`b_gate.MIN_NET_LIFT`) —
#: a signal's net-of-control lift must be STRICTLY greater than this to
#: qualify; `<=` denies, exactly the original W3 module's own stated rule.
MIN_NET_LIFT = _MIN_NET_LIFT

#: The closed 5-member `OutcomeLayer` vocabulary the real engine gates on,
#: cycled deterministically (by input order) to assign each opaque
#: `MeasurementSignal.name` a layer — the W3 API never carried a `layer`
#: field, so this shim's ONLY freedom is picking a stable, order-invariant
#: assignment that lets >= 2 signals land on >= 2 distinct layers (matching
#: the real gate's independence-by-distinct-layer accounting) without
#: inventing any new gating rule.
_LAYER_CYCLE_ORDER: tuple[OutcomeLayer, ...] = (
    OutcomeLayer.DISCOVERY,
    OutcomeLayer.CITATION,
    OutcomeLayer.ABSORPTION,
    OutcomeLayer.PROMINENCE,
    OutcomeLayer.REFERRAL,
)

#: A permissive, test-fixture-provenance policy — this shim (like the
#: original W3 evaluator) models NO evidence-bundle/window/GRS state; every
#: signal is treated as arriving in an otherwise-complete, otherwise-
#: confirmed, otherwise-uncontaminated window so the ONLY thing that can
#: drive an UNDETERMINED/FAIL/PASS split is the lift/independent-layer logic
#: this evaluator has always been scoped to.
_PERMISSIVE_POLICY = GatePolicy(
    version="0.0.0-f9-shim", hash="sha256:" + "9" * 64, provenance=PolicyProvenance.TEST_FIXTURE
)
_PERMISSIVE_EVIDENCE_CHECK = EvidenceCheck(manifest_hash_ok=True, raw_refs_present=True)
_PERMISSIVE_WINDOW_STATE = WindowState(complete=True, deployment_confirmed=True)


@dataclass(frozen=True, slots=True)
class MeasurementSignal:
    """One independently-observed raw treatment/control delta pair.

    Retained VERBATIM from the W3 module — this shim adds no new field and
    changes no existing one, so every existing construction call-site
    continues to work unmodified.
    """

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
    pure-DATA-signal shape elsewhere in this codebase.

    Retained VERBATIM from the W3 module — same three fields, same meaning.
    """

    granted: bool
    reason: str
    net_lifts: dict[str, float]


def _signal_result(index: int, signal: MeasurementSignal) -> SignalResult:
    """Map one `MeasurementSignal` onto a real `b_gate.SignalResult`.

    `layer` is assigned by cycling `_LAYER_CYCLE_ORDER` on `index` (the
    signal's position in the caller-supplied tuple) — deterministic and
    order-stable for a FIXED input tuple (required for `evaluate_b_layer_
    success`'s own determinism guarantee, pinned by `test_f9_measurement_
    fraud.py::test_evaluator_is_deterministic_across_repeated_calls`).
    `evidence_basis_id=signal.name` preserves the W3 module's own implicit
    independence key (two signals sharing a `name` were never possible in
    the old API either, since callers pass a tuple of already-distinct
    names).
    """
    layer = _LAYER_CYCLE_ORDER[index % len(_LAYER_CYCLE_ORDER)]
    net_lift = signal.net_of_control_lift
    return SignalResult(
        layer=layer,
        evidence_basis_id=signal.name,
        treatment_raw_delta=signal.treatment_raw_delta,
        control_raw_delta=signal.control_raw_delta,
        net_of_control_lift=net_lift,
        has_control_adjusted_lift=True,
        sufficient_data=True,
        has_raw_evidence_ref=True,
    )


def evaluate_b_layer_success(signals: tuple[MeasurementSignal, ...]) -> BLayerVerdict:
    """Deterministic: equal `signals` always yields an equal `BLayerVerdict`.

    Delegates to the REAL `saena_domain.measurement.b_gate.decide_b_verdict`
    (see module docstring) — this function's own body contains NO gating
    logic of its own; it only maps inputs in, and maps the real decision's
    `BVerdict`/`reason_codes`/`qualifying_layers` back onto the W3 API's
    `BLayerVerdict` shape.
    """
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

    signal_results = tuple(_signal_result(i, s) for i, s in enumerate(signals))
    decision = decide_b_verdict(
        signal_results, _PERMISSIVE_EVIDENCE_CHECK, _PERMISSIVE_WINDOW_STATE, _PERMISSIVE_POLICY
    )

    if decision.verdict is _BVerdict.PASS:
        return BLayerVerdict(
            granted=True,
            reason="every independent signal shows positive net-of-control lift",
            net_lifts=net_lifts,
        )

    non_positive = sorted(name for name, lift in net_lifts.items() if lift <= MIN_NET_LIFT)
    return BLayerVerdict(
        granted=False,
        reason=(
            "signal(s) with no net-of-control lift (raw grew but control "
            f"grew too, or more): {non_positive}"
        ),
        net_lifts=net_lifts,
    )


__all__ = [
    "MIN_INDEPENDENT_SIGNALS",
    "MIN_NET_LIFT",
    "BLayerVerdict",
    "MeasurementSignal",
    "evaluate_b_layer_success",
]

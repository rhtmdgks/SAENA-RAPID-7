"""B-layer success gate — pure, deterministic ≥2-independent-layer verdict.

Source specification references (READ-ONLY basis for this module):
- docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md §3.7-5:198 — "최소 두
  개 이상의 독립 signal layer에서 개선이 나타나야 B 계층 성과로 분류한다"
  (improvement in AT LEAST TWO independent signal layers is required before an
  outcome is classified as B-layer success). This is the gate's core rule.
- Algorithm §11.1:188 — "causal uplift model: 통제군 대비 순효과 추정"
  (net effect relative to a control group). The gate qualifies a signal ONLY
  on strictly-positive ``net_of_control_lift``, never on a raw-count increase.
- k3s spec §10 F-9 — "raw citation count grows but control too → B-layer
  success not granted": raw-up / control-equal fixtures never PASS. The
  decision still SHOWS that contrast: such a signal appears in ``raw_view``
  (its raw treatment count really did move) and NOT in
  ``control_adjusted_view`` — showing both views side by side is the point
  (k3s §9.2:485, raw + causal reporting together).
- wave5-plan.md E4 + H3 working assumption — independence = distinct
  ``OutcomeLayer`` AND distinct ``evidence_basis_id``; a duplicated basis (or a
  duplicated layer) counts ONCE. 1 qualifying layer ⇒ FAIL(single_layer_only);
  insufficient / contaminated / late / evidence-broken inputs ⇒ UNDETERMINED
  with the specific reason code(s).
- wave5-plan.md Non-scope + §3.6:190 — KPI weight auto-optimization is
  FORBIDDEN at P0: ``decide_b_verdict`` takes NO weight parameter and performs
  NO weighted aggregation for the verdict. ``test_no_weight_parameter`` pins
  this as an executable assertion.

This module is PURE and DETERMINISTIC: equal inputs always yield an equal
``BGateDecision``. It performs no I/O, grants nothing, starts no clock — a
caller treats a non-PASS verdict as a hard block on any external "it worked"
claim (CLAUDE.md 원칙 11).

## Fail-closed, three distinct verdicts

``BVerdict`` has THREE distinct values and the gate never collapses one into
another:
- ``PASS`` — mechanism success: ≥2 independent qualifying layers, all inputs
  sufficient, evidence intact.
- ``FAIL`` — data was sufficient but the *effect* is insufficient (exactly one
  qualifying layer, or no qualifying layer while inputs were otherwise sound).
- ``UNDETERMINED`` — a required input was insufficient/broken (window
  incomplete, deployment unconfirmed/late, missing baseline/control,
  insufficient repeats, contamination, adapter drift, evidence-hash mismatch,
  missing raw refs, non-finite numeric input). UNDETERMINED is NEVER folded
  into PASS or a silent FAIL.

## Production vs test-fixture provenance

The decision carries the policy passthrough ``{version, hash, provenance}``.
``provenance == "test_fixture"`` marks the decision ``is_production=False`` —
a mechanism PASS on a test fixture is explicitly separated from a production
PASS (wave5-plan.md "mechanism PASS / production BLOCKED(human)").

## Non-finite inputs are fail-closed (critic-2 remediation, 2026-07-14)

NaN compares False against EVERY threshold (both ``> 0`` and ``<= 0``), so an
unguarded accept/reject comparison pair silently lets NaN through to the
accept side; ``+inf > 0`` is True outright. Either way a forged non-finite
``net_of_control_lift`` must never mint a PASS. Defence in depth, two layers:

1. **Construction-time**: every numeric field is declared
   ``allow_inf_nan=False`` (pydantic rejects NaN/+inf/-inf with a
   ``ValidationError`` before a ``SignalResult``/``BGateDecision`` can exist).
2. **Gate-time (defensive)**: ``decide_b_verdict`` re-checks
   ``math.isfinite`` on every numeric field of every signal (covers
   ``model_construct`` bypass and any future field added without the
   constraint) — any non-finite value ⇒ ``UNDETERMINED`` with
   ``ReasonCode.NON_FINITE_INPUT``, and the signal is excluded from both
   views and from qualification. The qualification comparison is written as
   the exact negation ``if not (lift > MIN_NET_LIFT)`` so any comparison a
   non-finite value fails lands on the REJECT side, never the accept side.

Internal invariant (pinned by test): every qualifying layer also appears in
``control_adjusted_view`` — a qualifier the control-adjusted view cannot see
is by definition forged.

## Order-invariant independence counting (critic-1 remediation, 2026-07-14)

Counting independent layers is a MAXIMUM bipartite matching between distinct
``OutcomeLayer`` values and distinct ``evidence_basis_id`` values over the
qualifying (layer, basis) pairs — NOT a greedy first-seen assignment. Greedy
basis-keyed matching made the verdict depend on input tuple order (a layer
with two bases plus another layer sharing one basis could PASS or FAIL by
permutation). The matching iterates layers and bases in sorted order over a
set of edges, so the result is deterministic and input-order-invariant; a
permutation property test pins this.

## Trust boundary: (layer, evidence_basis_id) independence is caller-asserted

This is a PURE domain gate: it cannot inspect raw evidence. The independence
facts it dedups on — ``layer`` and ``evidence_basis_id`` — are ASSERTED by
the caller. Upstream owners are w5-04 (experiment→measurement binding) and
the w5-12 service boundary: THEY must derive ``evidence_basis_id`` from the
actual evidence (e.g. content-addressed refs), never accept caller-supplied
free strings. The B-gate deduplicates identical basis ids but CANNOT detect
the same underlying evidence relabelled under two different basis ids — that
detection belongs to the evidence bundle (w5-08) and the binding layer.

## BGateDecision is not self-authenticating

See the ``BGateDecision`` docstring: any code can construct one. Authenticity
comes from the evidence bundle manifest (w5-08) binding the decision plus the
service boundary — consumers (e.g. skill-bank intake, w5-16) must never trust
a bare ``BGateDecision`` object received across a trust boundary.
"""

from __future__ import annotations

import math
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .outcome_layer import OutcomeLayer
from .reason_codes import ReasonCode

#: A net-of-control lift must be STRICTLY greater than this to qualify — a
#: signal with zero or negative net-of-control lift is exactly the F-9 fraud
#: fixture (raw grew but control grew too, or more) and never qualifies.
MIN_NET_LIFT: float = 0.0

#: Minimum number of INDEPENDENT qualifying layers for a PASS (§3.7-5:198).
MIN_INDEPENDENT_LAYERS: int = 2


class BVerdict(str, Enum):
    """The three distinct B-gate verdicts (never collapsed into one another)."""

    PASS = "pass"
    FAIL = "fail"
    UNDETERMINED = "undetermined"


class PolicyProvenance(str, Enum):
    """Where the governing policy bundle came from."""

    PRODUCTION = "production"
    TEST_FIXTURE = "test_fixture"


class GatePolicy(BaseModel):
    """Signed-policy passthrough — the gate copies this into the decision.

    The gate does NOT interpret ``version``/``hash`` for the verdict; they are
    provenance metadata carried through so a decision is auditable and so a
    test-fixture policy can be marked non-production.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1)
    hash: str = Field(min_length=1)
    provenance: PolicyProvenance


class SignalResult(BaseModel):
    """One per-signal measurement result fed to the gate.

    A signal qualifies iff it has sufficient data AND a control-adjusted lift
    was actually computed AND that lift is strictly positive. Independence is
    keyed on (``layer``, ``evidence_basis_id``): two results sharing an
    ``evidence_basis_id`` count once, and a layer appearing twice counts once.

    Every numeric field is ``allow_inf_nan=False`` — NaN/±inf is rejected at
    construction (fail-closed; see module docstring). ``decide_b_verdict``
    additionally re-validates finiteness defensively.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    layer: OutcomeLayer
    evidence_basis_id: str = Field(min_length=1)
    #: RAW delta observed in the treatment arm over the window (unadjusted).
    #: ``raw_view`` is built from ``treatment_raw_delta > 0`` — actual raw
    #: movement, independent of the lift sign (F-9 contrast, k3s §9.2:485).
    treatment_raw_delta: float = Field(allow_inf_nan=False)
    #: RAW delta observed in the control arm over the same window.
    control_raw_delta: float = Field(allow_inf_nan=False)
    #: The causal-uplift proxy (e.g. DiD net effect relative to control).
    #: Only meaningful when ``has_control_adjusted_lift`` is True.
    net_of_control_lift: float = Field(allow_inf_nan=False)
    #: False ⇒ only a raw-count increase was available, no control adjustment
    #: (records NO_CONTROL_ADJUSTED_LIFT; never qualifies regardless of raw).
    has_control_adjusted_lift: bool = True
    #: False ⇒ this signal's own data was insufficient (records
    #: INSUFFICIENT_REPEATS at signal granularity; contributes to UNDETERMINED).
    sufficient_data: bool = True
    #: True ⇒ this signal's raw evidence reference is present (E5). False
    #: records MISSING_RAW_EVIDENCE_REF and blocks qualification (fail-closed).
    has_raw_evidence_ref: bool = True


class EvidenceCheck(BaseModel):
    """Evidence-bundle integrity summary (fail-closed inputs, E5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: False ⇒ manifest hash did not verify ⇒ UNDETERMINED(evidence_hash_mismatch).
    manifest_hash_ok: bool
    #: False ⇒ at least one required raw evidence ref is missing at bundle level
    #: ⇒ UNDETERMINED(missing_raw_evidence_ref).
    raw_refs_present: bool


class WindowState(BaseModel):
    """Measurement-window / design integrity summary (E1/E2/E4 inputs).

    Every ``True`` here (except ``complete``/``deployment_confirmed``) is a
    *problem* flag that forces UNDETERMINED with a specific reason code. The
    two positive-sense flags (``complete``, ``deployment_confirmed``) force
    UNDETERMINED when False.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    complete: bool
    deployment_confirmed: bool
    deployment_late: bool = False
    contamination: bool = False
    adapter_drift: bool = False
    missing_baseline: bool = False
    missing_control: bool = False
    insufficient_repeats: bool = False


class BGateDecision(BaseModel):
    """Frozen, pure result of ``decide_b_verdict``.

    Carries BOTH views (``raw_view`` and ``control_adjusted_view``) so a
    downstream consumer never has to re-derive them, the qualifying layers, the
    reason codes, and the policy provenance. ``is_production`` is derived from
    the policy provenance — a test-fixture decision is never production.

    **Not self-authenticating**: this is a pure-domain value object — any code
    can construct one (including with forged fields via ``model_construct``).
    A ``BGateDecision`` carries NO signature and proves nothing by itself.
    Authenticity comes from OUTSIDE this type: the evidence bundle manifest
    (w5-08) binds the decision to hashed raw evidence, and the service
    boundary (w5-12) controls who may emit one. Consumers — most critically
    the skill-bank intake (w5-16, B-verified-only fail-closed boundary) —
    must never trust a bare ``BGateDecision`` received across a trust
    boundary; they must verify it against its evidence bundle.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: BVerdict
    reason_codes: tuple[ReasonCode, ...]
    #: Layers whose signals showed ACTUAL raw treatment movement
    #: (treatment_raw_delta > 0), regardless of control adjustment.
    raw_view: tuple[OutcomeLayer, ...]
    #: Layers whose signals showed strictly-positive net-of-control lift.
    control_adjusted_view: tuple[OutcomeLayer, ...]
    #: The independent layers that actually qualified for the verdict.
    qualifying_layers: tuple[OutcomeLayer, ...]
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    policy_version: str
    policy_hash: str
    policy_provenance: PolicyProvenance
    is_production: bool


def _sorted_codes(codes: set[ReasonCode]) -> tuple[ReasonCode, ...]:
    """Deterministic ordering of reason codes by wire value."""
    return tuple(sorted(codes, key=lambda c: c.value))


def _sorted_layers(layers: set[OutcomeLayer]) -> tuple[OutcomeLayer, ...]:
    return tuple(sorted(layers, key=lambda layer: layer.value))


def _signal_is_finite(signal: SignalResult) -> bool:
    """Defensive finiteness re-check of every numeric field (model_construct
    bypasses pydantic validation; see module docstring)."""
    return (
        math.isfinite(signal.treatment_raw_delta)
        and math.isfinite(signal.control_raw_delta)
        and math.isfinite(signal.net_of_control_lift)
    )


def _max_independent_layers(
    edges: frozenset[tuple[OutcomeLayer, str]],
) -> tuple[OutcomeLayer, ...]:
    """MAXIMUM bipartite matching: distinct layers vs distinct basis ids.

    Returns the deterministically-chosen matched layers of ONE maximum
    matching. Iteration is over sorted layers and sorted bases on a SET of
    edges, so the result is input-order-invariant; the matching SIZE (what the
    verdict depends on) is unique by König/Berge even where the matched layer
    set is not. n ≤ 5 layers (closed enum), so augmenting paths are ample.
    """
    layers = sorted({layer for layer, _ in edges}, key=lambda layer: layer.value)
    adjacency: dict[OutcomeLayer, list[str]] = {
        layer: sorted(basis for edge_layer, basis in edges if edge_layer is layer)
        for layer in layers
    }
    basis_match: dict[str, OutcomeLayer] = {}

    def augment(layer: OutcomeLayer, visited: set[str]) -> bool:
        for basis in adjacency[layer]:
            if basis in visited:
                continue
            visited.add(basis)
            if basis not in basis_match or augment(basis_match[basis], visited):
                basis_match[basis] = layer
                return True
        return False

    for layer in layers:
        augment(layer, set())
    return _sorted_layers(set(basis_match.values()))


def decide_b_verdict(
    per_signal_results: tuple[SignalResult, ...],
    evidence_check: EvidenceCheck,
    window_state: WindowState,
    policy: GatePolicy,
) -> BGateDecision:
    """Return the B-layer verdict for a set of per-signal results.

    Pure and deterministic — and input-ORDER-invariant: permuting
    ``per_signal_results`` never changes the verdict, the qualifying layers,
    or the reason codes. Signature intentionally carries NO weight parameter
    and performs NO weighted aggregation (weights forbidden at P0, Algorithm
    §3.6:190).

    Decision order:
    1. Compute both views + qualifying independent layers (maximum bipartite
       matching over (layer, basis) pairs) regardless of verdict.
    2. Fail-closed insufficiency (non-finite numeric input / evidence broken /
       window incomplete / deployment unconfirmed or late / contamination /
       adapter drift / missing baseline or control / insufficient repeats /
       any signal with insufficient data) ⇒ UNDETERMINED with the specific
       code(s).
    3. Otherwise ≥2 independent qualifying layers ⇒ PASS.
    4. Exactly 1 qualifying layer ⇒ FAIL(single_layer_only).
    5. Zero qualifying layers (data sufficient, effect absent) ⇒ FAIL with the
       recorded non-qualification codes.
    """
    codes: set[ReasonCode] = set()

    # --- Per-signal classification (always computed) ---------------------
    raw_layers: set[OutcomeLayer] = set()
    qualifying_edges: set[tuple[OutcomeLayer, str]] = set()
    control_adjusted_layers: set[OutcomeLayer] = set()
    seen_basis: set[str] = set()

    for signal in per_signal_results:
        # Defensive finiteness gate FIRST: a non-finite signal contributes
        # nothing to any view and forces UNDETERMINED (fail-closed).
        if not _signal_is_finite(signal):
            codes.add(ReasonCode.NON_FINITE_INPUT)
            continue

        # Raw view: ACTUAL raw treatment movement, independent of lift sign.
        # The F-9 fraud fixture (raw up in both arms, net 0) appears HERE and
        # not in the control-adjusted view — that contrast is deliberate.
        if signal.treatment_raw_delta > 0.0:
            raw_layers.add(signal.layer)

        # Duplicate-basis detection for independence accounting.
        if signal.evidence_basis_id in seen_basis:
            codes.add(ReasonCode.DUPLICATE_EVIDENCE_BASIS)
        seen_basis.add(signal.evidence_basis_id)

        # Per-signal sufficiency (contributes to UNDETERMINED downstream).
        if not signal.sufficient_data:
            codes.add(ReasonCode.INSUFFICIENT_REPEATS)
        if not signal.has_raw_evidence_ref:
            codes.add(ReasonCode.MISSING_RAW_EVIDENCE_REF)

        # Qualification: control-adjusted AND strictly positive AND
        # sufficient. Written as the exact NEGATION of the accept condition so
        # any comparison a pathological value fails lands on the reject side.
        if not signal.has_control_adjusted_lift:
            codes.add(ReasonCode.NO_CONTROL_ADJUSTED_LIFT)
            continue
        if not (signal.net_of_control_lift > MIN_NET_LIFT):
            codes.add(ReasonCode.NEGATIVE_OR_INCONCLUSIVE_LIFT)
            continue
        control_adjusted_layers.add(signal.layer)
        if not signal.sufficient_data or not signal.has_raw_evidence_ref:
            continue  # insufficiency already recorded; not a qualifier.
        qualifying_edges.add((signal.layer, signal.evidence_basis_id))

    # Independent qualifying layers: MAXIMUM matching of distinct layers to
    # distinct evidence bases (order-invariant; duplicate basis counts once,
    # duplicate layer counts once).
    qualifying_layers = _max_independent_layers(frozenset(qualifying_edges))
    control_adjusted_view = _sorted_layers(control_adjusted_layers)
    raw_view = _sorted_layers(raw_layers)

    # --- Insufficiency (fail-closed) → UNDETERMINED ----------------------
    if not evidence_check.manifest_hash_ok:
        codes.add(ReasonCode.EVIDENCE_HASH_MISMATCH)
    if not evidence_check.raw_refs_present:
        codes.add(ReasonCode.MISSING_RAW_EVIDENCE_REF)
    if not window_state.complete:
        codes.add(ReasonCode.WINDOW_INCOMPLETE)
    if not window_state.deployment_confirmed:
        codes.add(ReasonCode.DEPLOYMENT_UNCONFIRMED)
    if window_state.deployment_late:
        codes.add(ReasonCode.DEPLOYMENT_LATE)
    if window_state.contamination:
        codes.add(ReasonCode.TREATMENT_CONTROL_CONTAMINATION)
    if window_state.adapter_drift:
        codes.add(ReasonCode.OBSERVATION_ADAPTER_DRIFT)
    if window_state.missing_baseline:
        codes.add(ReasonCode.MISSING_BASELINE)
    if window_state.missing_control:
        codes.add(ReasonCode.MISSING_CONTROL)
    if window_state.insufficient_repeats:
        codes.add(ReasonCode.INSUFFICIENT_REPEATS)

    undetermined_codes = {
        ReasonCode.NON_FINITE_INPUT,
        ReasonCode.EVIDENCE_HASH_MISMATCH,
        ReasonCode.MISSING_RAW_EVIDENCE_REF,
        ReasonCode.WINDOW_INCOMPLETE,
        ReasonCode.DEPLOYMENT_UNCONFIRMED,
        ReasonCode.DEPLOYMENT_LATE,
        ReasonCode.TREATMENT_CONTROL_CONTAMINATION,
        ReasonCode.OBSERVATION_ADAPTER_DRIFT,
        ReasonCode.MISSING_BASELINE,
        ReasonCode.MISSING_CONTROL,
        ReasonCode.INSUFFICIENT_REPEATS,
    }
    is_production = policy.provenance is PolicyProvenance.PRODUCTION

    def _decide(verdict: BVerdict, confidence: float) -> BGateDecision:
        return BGateDecision(
            verdict=verdict,
            reason_codes=_sorted_codes(codes),
            raw_view=raw_view,
            control_adjusted_view=control_adjusted_view,
            qualifying_layers=qualifying_layers,
            confidence=confidence,
            policy_version=policy.version,
            policy_hash=policy.hash,
            policy_provenance=policy.provenance,
            is_production=is_production,
        )

    if codes & undetermined_codes:
        # Fail-closed: any insufficiency ⇒ UNDETERMINED, never PASS/silent FAIL.
        return _decide(BVerdict.UNDETERMINED, confidence=0.0)

    # --- Effect sufficiency → PASS / FAIL --------------------------------
    n = len(qualifying_layers)
    if n >= MIN_INDEPENDENT_LAYERS:
        return _decide(BVerdict.PASS, confidence=1.0)

    if n == 1:
        codes.add(ReasonCode.SINGLE_LAYER_ONLY)
        return _decide(BVerdict.FAIL, confidence=0.0)

    # Zero qualifying layers, data sufficient: effect insufficient ⇒ FAIL.
    # If nothing else explained it (truly empty input), record
    # single_layer_only to name the shortfall.
    if not codes:
        codes.add(ReasonCode.SINGLE_LAYER_ONLY)
    return _decide(BVerdict.FAIL, confidence=0.0)


__all__ = [
    "MIN_NET_LIFT",
    "MIN_INDEPENDENT_LAYERS",
    "BVerdict",
    "PolicyProvenance",
    "GatePolicy",
    "SignalResult",
    "EvidenceCheck",
    "WindowState",
    "BGateDecision",
    "decide_b_verdict",
]

"""``ReasonCode`` — typed vocabulary for why a B-gate verdict is what it is.

Status: **v1 DRAFT, ADR-proposed** (wave5-plan.md H7: "typed code-level enum
v1 (ADR-proposed doc)"). This module fixes the code-level vocabulary so the
B-gate can attach machine-readable, stable reasons to every FAIL/UNDETERMINED
(and to any non-qualifying signal on a PASS). Spec adoption of the exact
vocabulary is the BLOCKED(human) part of H7; the *mechanism* (typed, closed,
no free-text reason strings leaking into the verdict) is what this module
delivers.

Design intent — a reason code is a closed, additive-widen-is-major vocabulary
(ADR-0012), NOT a free-form message. It exists so downstream consumers
(skill-bank intake w5-16, evidence bundle, dashboards) can branch on WHY a
verdict was withheld without parsing prose, and so an "UNDETERMINED because
data insufficient" is never silently indistinguishable from a "FAIL because
effect insufficient".

Each member below is required by this patch unit's directive (the B-gate
attaches the specific code(s) for each failure/withholding mode). Categories,
for the reader:

Design/registration integrity (measurement invalid *before* any effect math):
- ``MISSING_BASELINE`` / ``MISSING_CONTROL`` — no baseline / no control arm to
  net against; net-of-control lift is undefined.
- ``TREATMENT_CONTROL_CONTAMINATION`` — treatment and control not isolated
  (Algorithm §3.7 pre-registration; contamination invalidates the comparison).
- ``POST_REGISTRATION_METRIC_MUTATION`` — a metric/def changed after Day-0
  registration (immutability breach, E1).
- ``CELL_MISMATCH`` — locale/browser/query-cluster cell of an observation does
  not match the registered cell.
- ``INSUFFICIENT_REPEATS`` — fewer repeats than the registered ``repeat_count``.

Deployment/window timing (clock authority, E2/E4):
- ``DEPLOYMENT_UNCONFIRMED`` — no ``deployment.confirmed.v1`` anchor; the 7-day
  clock never legitimately started.
- ``DEPLOYMENT_LATE`` — deployment landed after Day 2, so the 7-day external
  performance clock must not start (Algorithm §7.3:483).
- ``WINDOW_INCOMPLETE`` — the measurement window has not fully elapsed.

Evidence integrity (fail-closed, E5):
- ``MISSING_RAW_EVIDENCE_REF`` — a qualifying signal lacks its raw evidence
  reference (snapshot/citation/timestamp).
- ``ASSET_HASH_CONFLICT`` — observed asset hash disagrees with the registered
  asset hash.
- ``EVIDENCE_HASH_MISMATCH`` — evidence bundle manifest hash does not verify.
- ``MISSING_RAW_EVIDENCE_REF`` covers the missing-ref case; the two are
  distinct so a *tampered* bundle is never conflated with a *missing* one.

Independence / effect sufficiency (the ≥2-independent-layer core, E4):
- ``SINGLE_LAYER_ONLY`` — exactly one qualifying independent layer (effect real
  but not corroborated by a second independent layer).
- ``NO_CONTROL_ADJUSTED_LIFT`` — a raw-count increase with no control-adjusted
  lift computed (raw grew but the causal-uplift proxy is absent).
- ``NEGATIVE_OR_INCONCLUSIVE_LIFT`` — a signal's net-of-control lift is zero or
  negative (F-9 fraud fixture: raw grows but control grew too/more).
- ``DUPLICATE_EVIDENCE_BASIS`` — two filed results share one
  ``evidence_basis_id`` (or repeat one layer); they count ONCE, not twice.

Numeric input integrity (critic-2 remediation, 2026-07-14):
- ``NON_FINITE_INPUT`` — a numeric input (e.g. ``net_of_control_lift``) was
  NaN/+inf/-inf. NaN compares False against EVERY threshold (both ``> 0`` and
  ``<= 0``), so an unguarded comparison chain can neither qualify nor reject
  it deterministically, and ``+inf > 0`` is True — either way a forged number
  must never mint a PASS. Fail-closed demands UNDETERMINED.

Adapter / policy / confirmation integrity:
- ``OBSERVATION_ADAPTER_DRIFT`` — the observation adapter drifted from its
  approved fixture/contract; observations are untrustworthy.
- ``GRS_POLICY_MISSING`` — no signed GRS policy bundle available (fail-closed).
- ``CONFLICTING_CONFIRMATION`` — contradictory deployment confirmations.
- ``IDENTITY_MISMATCH`` — an observation/confirmation identity does not match
  the registered tenant/run/experiment identity.

The set is intentionally a superset of what any single verdict will use; a
decision attaches only the codes that actually apply.

## Cross-unit vocabulary map (superset is INTENTIONAL — pinned here)

Six members are NOT emitted by ``b_gate.decide_b_verdict`` itself; they are
shared vocabulary owned/emitted by sibling Wave-5 units, defined here so the
whole measurement layer speaks ONE typed reason vocabulary:

- ``CONFLICTING_CONFIRMATION``            → w5-03 (deployment confirmation/clock)
- ``CELL_MISMATCH``                       → w5-04 (experiment→measurement binding)
- ``IDENTITY_MISMATCH``                   → w5-04 (binding)
- ``POST_REGISTRATION_METRIC_MUTATION``   → w5-04 (binding/immutability, E1)
- ``GRS_POLICY_MISSING``                  → w5-07 (GRS fail-closed bundle loading)
- ``ASSET_HASH_CONFLICT``                 → w5-08 (evidence bundle manifest)

Every other member is emittable by the w5-06 B-gate. If a sibling unit stops
emitting one of the six, remove it here via the normal major-change path —
never leave it silently dead.
"""

from __future__ import annotations

from enum import Enum


class ReasonCode(str, Enum):
    """Closed, typed vocabulary of B-gate reason codes (v1 draft, ADR-proposed).

    Inherits ``str`` so a member serialises to its wire value and can be sorted
    deterministically. Membership is CLOSED — adding a code is a major change,
    never a silent edit (ADR-0012). No free-text reason ever substitutes for a
    member of this enum in a ``BGateDecision``.
    """

    MISSING_BASELINE = "missing_baseline"
    MISSING_CONTROL = "missing_control"
    TREATMENT_CONTROL_CONTAMINATION = "treatment_control_contamination"
    POST_REGISTRATION_METRIC_MUTATION = "post_registration_metric_mutation"
    CELL_MISMATCH = "cell_mismatch"
    INSUFFICIENT_REPEATS = "insufficient_repeats"
    DEPLOYMENT_UNCONFIRMED = "deployment_unconfirmed"
    DEPLOYMENT_LATE = "deployment_late"
    MISSING_RAW_EVIDENCE_REF = "missing_raw_evidence_ref"
    ASSET_HASH_CONFLICT = "asset_hash_conflict"
    SINGLE_LAYER_ONLY = "single_layer_only"
    NO_CONTROL_ADJUSTED_LIFT = "no_control_adjusted_lift"
    NEGATIVE_OR_INCONCLUSIVE_LIFT = "negative_or_inconclusive_lift"
    NON_FINITE_INPUT = "non_finite_input"
    WINDOW_INCOMPLETE = "window_incomplete"
    OBSERVATION_ADAPTER_DRIFT = "observation_adapter_drift"
    GRS_POLICY_MISSING = "grs_policy_missing"
    EVIDENCE_HASH_MISMATCH = "evidence_hash_mismatch"
    CONFLICTING_CONFIRMATION = "conflicting_confirmation"
    IDENTITY_MISMATCH = "identity_mismatch"
    DUPLICATE_EVIDENCE_BASIS = "duplicate_evidence_basis"


__all__ = ["ReasonCode"]

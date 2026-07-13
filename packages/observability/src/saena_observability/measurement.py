"""Wave 5 (Measurement / B-layer) metric/span name constants + attribute
allowlist helper (w5-17).

Registers the `saena.<domain>.<name>` metric names and
`saena.<capability>.<operation>` span names for the measurement pipeline
named in the Wave 5 plan (`docs/architecture/wave5-plan.md`), whose five
deliverables are:

- deployment-confirmation + trusted 7-day clock
  (`saena_domain.measurement.confirmation` / `.clock`, w5-03; the sole
  clock-start authority, Algorithm §7.3)
- difference-in-differences (DiD) attribution
  (`saena_domain.measurement.did`, w5-05; Algorithm §3.7-4 — DETERMINISTIC
  DiD is P0 and, unlike Wave 4, IN SCOPE for Wave 5)
- outcome-layer B-gate + reason codes
  (`saena_domain.measurement.b_gate` / `.reason_codes`, w5-06; Algorithm
  §3.7-5 — a B-layer verdict requires ≥2 independent signal layers)
- evidence-bundle seal / provenance
  (`saena_domain.measurement.evidence`, w5-08; Algorithm §3.7-3 / §11.3)
- GRS eligibility (`saena_domain.measurement.grs`, w5-07; k3s Gate C —
  fail-closed policy interface; production thresholds stay BLOCKED(human))
- B-verified-only skill-bank intake boundary
  (services/experimentation/strategy-skill-bank-service, w5-16)

Every name below is validated at import time via
`saena_observability.naming.validate_metric_name` /
`validate_span_name` — a typo that breaks the `saena.<domain>.<name>` /
`saena.<capability>.<operation>` shape fails at collection time, not
silently at emit time.

## Scope discipline — outcome MAGNITUDE stays out of telemetry

CLAUDE.md ("증거 없는 완료 선언 금지" / "Untrusted content") and
wave5-plan.md ("Raw customer query/content/secret in events/logs/audit
payloads" FORBIDDEN; "Unverified external-lift claims" FORBIDDEN) require
that telemetry never carry an outcome/effect/lift MAGNITUDE or an
unverified causal claim. This module honours that as follows:

- No metric here records an effect size, a DiD point estimate, a p-value, a
  lift/uplift number, or any B-verdict "strength". Everything is a COUNT
  (`*_total`), a GAUGE (`*`), or a latency HISTOGRAM (`*_duration_seconds`)
  — operational/health telemetry only.
- `saena.measurement.did_signals_evaluated_total` COUNTS how many signal
  inputs a DiD computation consumed; it is not the DiD result value.
- `saena.measurement.b_verdicts_total` counts verdicts partitioned by the
  low-cardinality `saena.measurement.verdict` label
  (`pass|fail|undetermined`), never by an effect magnitude.

## Divergence from the Wave 4 `_did_` name ban (documented, not silent)

The Wave 4 observability guard (`test_intelligence.py`
`FORBIDDEN_OUTCOME_TOKENS`) forbade the standalone `_did_` token in any
registered name, because DiD was explicitly OUT of Wave 4 scope. In
Wave 5 the DETERMINISTIC DiD engine is deliverable #1 (wave5-plan.md;
named CI gate `did-attribution`), so naming the *operation* of computing a
DiD attribution — `saena.measurement.compute_did_attribution`,
`saena.measurement.did_signals_evaluated_total` — is legitimate,
in-scope operational telemetry. The Wave-5 forbidden-token set below
(`FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS`) therefore continues to ban every
token that denotes an outcome/effect *value* (`lift`, `uplift`, `effect`,
`causal`, `estimate`, `delta`, `p_value`, `significance`,
`observed_value`) but deliberately does NOT ban `did` as an
operation-name segment. The distinction is magnitude-VALUE (still
forbidden) vs. operation-NAME (allowed): `test_measurement.py` pins both
halves as executable guards.

## Attribute discipline

This module also exposes `MEASUREMENT_ATTRIBUTE_NAMES`, the frozenset of
every `saena.*` attribute name a caller emitting one of these
spans/metrics/logs is expected to use (a subset of the full registry in
`registry/attributes.yaml` / `attributes.json` — the W0 core set plus the
w5-17 additions). This is a convenience constant only;
`saena_observability.redaction.decide_redaction` remains the single
enforcement point (allowlist-first against the full registry), not this
module.
"""

from __future__ import annotations

from saena_observability.naming import validate_metric_name, validate_span_name

# ---------------------------------------------------------------------------
# deployment confirmation + trusted 7-day clock (w5-03)
# ---------------------------------------------------------------------------

METRIC_CONFIRMATIONS_ACCEPTED_TOTAL = "saena.measurement.confirmations_accepted_total"
"""Counter: `deployment.confirmed.v1` confirmations accepted as a valid
clock-start signal (Algorithm §7.3 — the sole clock-start authority)."""

METRIC_CONFIRMATIONS_REJECTED_TOTAL = "saena.measurement.confirmations_rejected_total"
"""Counter: confirmations rejected, partitioned by the low-cardinality
`saena.measurement.reason_code` label (e.g. late/backdate/cross-tenant/
replay/identity — never a raw confirmer identity or query)."""

METRIC_WINDOWS_STARTED_TOTAL = "saena.measurement.windows_started_total"
"""Counter: 7-day external-performance measurement windows started (a
window starts iff a valid `deployment.confirmed.v1` was accepted)."""

SPAN_CONFIRM_DEPLOYMENT = "saena.measurement.confirm_deployment"
"""Span: validate + record one `deployment.confirmed.v1` confirmation."""

SPAN_START_WINDOW = "saena.measurement.start_window"
"""Span: start the 7-day external-performance clock/window."""

# ---------------------------------------------------------------------------
# difference-in-differences (DiD) attribution (w5-05)
# ---------------------------------------------------------------------------

METRIC_DID_COMPUTATIONS_TOTAL = "saena.measurement.did_computations_total"
"""Counter: DiD attribution computations completed, by outcome
(success/insufficient-data/error). A COUNT of runs — never the DiD result
value (no effect size / point estimate is ever emitted, see module
docstring)."""

METRIC_DID_SIGNALS_EVALUATED_TOTAL = "saena.measurement.did_signals_evaluated_total"
"""Counter: signal inputs consumed across DiD computations. Counts HOW
MANY signals were evaluated, not their values or the resulting estimate."""

METRIC_DID_COMPUTE_DURATION_SECONDS = "saena.measurement.did_compute_duration_seconds"
"""Histogram: wall-clock duration of one DiD attribution computation."""

SPAN_COMPUTE_DID_ATTRIBUTION = "saena.measurement.compute_did_attribution"
"""Span: one deterministic DiD attribution computation (w5-05). Names the
OPERATION of computing the attribution — carries no effect-magnitude
attribute (see module docstring's divergence note)."""

# ---------------------------------------------------------------------------
# outcome-layer B-gate + reason codes (w5-06)
# ---------------------------------------------------------------------------

METRIC_B_VERDICTS_TOTAL = "saena.measurement.b_verdicts_total"
"""Counter: B-layer gate verdicts, partitioned by the low-cardinality
`saena.measurement.verdict` label (exactly `pass|fail|undetermined`). A
count of verdicts, never a verdict "strength"/effect magnitude."""

METRIC_UNDETERMINED_REASONS_TOTAL = "saena.measurement.undetermined_reasons_total"
"""Counter: UNDETERMINED B-verdicts, partitioned by the low-cardinality
`saena.measurement.reason_code` label (bounded closed enum — insufficient/
contaminated/late/single-layer/etc.)."""

METRIC_INDEPENDENT_LAYERS_EVALUATED_TOTAL = "saena.measurement.independent_layers_evaluated_total"
"""Counter: independent signal layers evaluated by the B-gate. Counts
layers (a B-verdict requires ≥2 independent layers, Algorithm §3.7-5) —
never a per-layer effect value."""

SPAN_DECIDE_B_GATE = "saena.measurement.decide_b_gate"
"""Span: one outcome-layer B-gate decision (w5-06)."""

# ---------------------------------------------------------------------------
# evidence-bundle seal / provenance (w5-08)
# ---------------------------------------------------------------------------

METRIC_EVIDENCE_BUNDLES_SEALED_TOTAL = "saena.measurement.evidence_bundles_sealed_total"
"""Counter: evidence bundles sealed (manifest + provenance hash committed,
Algorithm §3.7-3 / §11.3)."""

METRIC_EVIDENCE_BUNDLE_SEAL_DURATION_SECONDS = (
    "saena.measurement.evidence_bundle_seal_duration_seconds"
)
"""Histogram: wall-clock duration of one evidence-bundle seal operation."""

SPAN_SEAL_EVIDENCE_BUNDLE = "saena.measurement.seal_evidence_bundle"
"""Span: seal one evidence bundle (snapshot + citation + timestamp + client
version + asset hash → manifest hash). No raw content in any attribute —
only `saena.measurement.evidence_bundle_id` (opaque) /
`saena.measurement.evidence_bundle_hash` (a hash)."""

# ---------------------------------------------------------------------------
# GRS eligibility (w5-07) — fail-closed policy interface
# ---------------------------------------------------------------------------

METRIC_GRS_ELIGIBILITY_EVALUATED_TOTAL = "saena.measurement.grs_eligibility_evaluated_total"
"""Counter: GRS eligibility evaluations, partitioned by
`saena.measurement.grs_decision` (closed enum, fail-closed default DENY —
production thresholds/credit mechanics stay BLOCKED(human), H1)."""

SPAN_GRS_ELIGIBILITY = "saena.measurement.grs_eligibility"
"""Span: one GRS eligibility evaluation against a signed policy bundle
(missing/unsigned ⇒ fail-closed DENY, w5-07)."""

# ---------------------------------------------------------------------------
# B-verified-only skill-bank intake boundary (w5-16)
# ---------------------------------------------------------------------------

METRIC_SKILL_BANK_INTAKE_TOTAL = "saena.measurement.skill_bank_intake_total"
"""Counter: skill-bank intake decisions, partitioned by
`saena.measurement.intake_decision` (closed enum: accepted|rejected —
fail-closed: only B-verified outcomes are consumed, w5-16)."""

SPAN_SKILL_BANK_INTAKE = "saena.measurement.skill_bank_intake"
"""Span: one B-verified-only skill-bank intake boundary decision (w5-16)."""

# ---------------------------------------------------------------------------
# Aggregated name sets
# ---------------------------------------------------------------------------

MEASUREMENT_METRIC_NAMES: frozenset[str] = frozenset(
    {
        METRIC_CONFIRMATIONS_ACCEPTED_TOTAL,
        METRIC_CONFIRMATIONS_REJECTED_TOTAL,
        METRIC_WINDOWS_STARTED_TOTAL,
        METRIC_DID_COMPUTATIONS_TOTAL,
        METRIC_DID_SIGNALS_EVALUATED_TOTAL,
        METRIC_DID_COMPUTE_DURATION_SECONDS,
        METRIC_B_VERDICTS_TOTAL,
        METRIC_UNDETERMINED_REASONS_TOTAL,
        METRIC_INDEPENDENT_LAYERS_EVALUATED_TOTAL,
        METRIC_EVIDENCE_BUNDLES_SEALED_TOTAL,
        METRIC_EVIDENCE_BUNDLE_SEAL_DURATION_SECONDS,
        METRIC_GRS_ELIGIBILITY_EVALUATED_TOTAL,
        METRIC_SKILL_BANK_INTAKE_TOTAL,
    }
)

MEASUREMENT_SPAN_NAMES: frozenset[str] = frozenset(
    {
        SPAN_CONFIRM_DEPLOYMENT,
        SPAN_START_WINDOW,
        SPAN_COMPUTE_DID_ATTRIBUTION,
        SPAN_DECIDE_B_GATE,
        SPAN_SEAL_EVIDENCE_BUNDLE,
        SPAN_GRS_ELIGIBILITY,
        SPAN_SKILL_BANK_INTAKE,
    }
)

#: Every `saena.*` attribute name relevant to the measurement workloads
#: above — the W0 core required-attribute set plus the w5-17 registry
#: additions (`attributes.yaml`). This is a documentation/convenience
#: constant; `saena_observability.redaction.decide_redaction` (driven by
#: the full `registry/attributes.json`) is the actual allowlist-enforcement
#: point, not this frozenset.
MEASUREMENT_ATTRIBUTE_NAMES: frozenset[str] = frozenset(
    {
        # W0 core (reused, never re-defined)
        "saena.tenant_id",
        "saena.run_id",
        "saena.engine_id",
        "saena.context",
        # experiment identity (reused from w4-15 — a measurement runs against
        # a pre-registered experiment; NOT re-defined here)
        "saena.experiment_id",
        # w5-17 additions
        "saena.measurement.window_id",
        "saena.measurement.verdict",
        "saena.measurement.reason_code",
        "saena.measurement.grs_decision",
        "saena.measurement.intake_decision",
        "saena.measurement.evidence_bundle_id",
        "saena.measurement.evidence_bundle_hash",
    }
)

#: Case-insensitive substrings that must never appear in a registered
#: measurement metric/span/attribute NAME because they denote an
#: outcome/effect/lift MAGNITUDE or an unverified causal-estimate VALUE
#: (CLAUDE.md "증거 없는 완료 선언 금지"; wave5-plan.md forbidden scope).
#: Deliberately a subset of the Wave-4/domain-model
#: `FORBIDDEN_OUTCOME_TOKENS`: the `did` operation-name token is NOT here,
#: because the deterministic DiD engine is an in-scope Wave-5 deliverable
#: and naming the *operation* of computing a DiD attribution is legitimate
#: (see module docstring "Divergence" note). The magnitude-VALUE tokens
#: below stay forbidden; `test_measurement.py` pins both halves.
FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS: tuple[str, ...] = (
    "lift",
    "uplift",
    "effect",
    "causal",
    "estimate",
    "delta",
    "p_value",
    "pvalue",
    "significance",
    "observed_value",
)

# Fail collection (not just at first call) if any name above regresses on
# the `saena.<domain>.<name>` / `saena.<capability>.<operation>` naming
# rule — a typo here must never silently ship.
for _metric_name in MEASUREMENT_METRIC_NAMES:
    validate_metric_name(_metric_name)
for _span_name in MEASUREMENT_SPAN_NAMES:
    validate_span_name(_span_name)
del _metric_name, _span_name


__all__ = [
    "FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS",
    "MEASUREMENT_ATTRIBUTE_NAMES",
    "MEASUREMENT_METRIC_NAMES",
    "MEASUREMENT_SPAN_NAMES",
    "METRIC_B_VERDICTS_TOTAL",
    "METRIC_CONFIRMATIONS_ACCEPTED_TOTAL",
    "METRIC_CONFIRMATIONS_REJECTED_TOTAL",
    "METRIC_DID_COMPUTATIONS_TOTAL",
    "METRIC_DID_COMPUTE_DURATION_SECONDS",
    "METRIC_DID_SIGNALS_EVALUATED_TOTAL",
    "METRIC_EVIDENCE_BUNDLES_SEALED_TOTAL",
    "METRIC_EVIDENCE_BUNDLE_SEAL_DURATION_SECONDS",
    "METRIC_GRS_ELIGIBILITY_EVALUATED_TOTAL",
    "METRIC_INDEPENDENT_LAYERS_EVALUATED_TOTAL",
    "METRIC_SKILL_BANK_INTAKE_TOTAL",
    "METRIC_UNDETERMINED_REASONS_TOTAL",
    "METRIC_WINDOWS_STARTED_TOTAL",
    "SPAN_COMPUTE_DID_ATTRIBUTION",
    "SPAN_CONFIRM_DEPLOYMENT",
    "SPAN_DECIDE_B_GATE",
    "SPAN_GRS_ELIGIBILITY",
    "SPAN_SEAL_EVIDENCE_BUNDLE",
    "SPAN_SKILL_BANK_INTAKE",
    "SPAN_START_WINDOW",
]

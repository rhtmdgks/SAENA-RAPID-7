"""``run_measurement`` — the w5-13 fail-closed measurement pipeline (pure).

Composes, IN ORDER, the Wave-5 domain modules already delivered by sibling
Stage-1 units — this module invents NO new measurement/statistics/verdict
logic; it only calls the existing functions in the right order and threads
their outputs into each other and into a sealed evidence bundle + outcome
record:

    1. GRS eligibility            saena_domain.measurement.grs
    2. binding                    saena_domain.measurement.binding
    3. deployment confirmation
       + window                   saena_domain.measurement.confirmation / clock
    4. DiD per signal              saena_domain.measurement.did
    5. B-gate verdict              saena_domain.measurement.b_gate
    6. evidence bundle seal        saena_domain.measurement.evidence
    7. ExperimentOutcome record
       (+ atomic, idempotent store) saena_domain.measurement.ports

Every step is fail-closed: a step that cannot honestly proceed records the
specific reason code(s) and the pipeline moves directly to sealing an honest
(possibly incomplete) evidence bundle and emitting an UNDETERMINED outcome —
it NEVER fabricates a missing input, NEVER upgrades UNDETERMINED to PASS/FAIL,
NEVER drops a reason code, and NEVER silently skips a later step's ledger
entry (a step that could not run still contributes a `missingness_report`).

## Step 1 — GRS eligibility runs FIRST, but never blocks the record

wave5-plan.md's directive is explicit: "GRS eligibility first (no bundle ->
UNDETERMINED(grs_policy_missing) recorded, pipeline still produces an honest
outcome record, never PASS)". GRS is evaluated once at the very top so its
decision is available to attach to evidence/outcome regardless of what
happens downstream, but a GRS DENY/UNDETERMINED does NOT short-circuit the
rest of the pipeline — every other step still runs so the outcome record is
as complete and honest as possible; only the FINAL `status` computation
folds the GRS result in (a non-ELIGIBLE GRS decision forces UNDETERMINED /
adds `GRS_POLICY_MISSING`, it can never promote a status to PASS on its own,
and it can never be silently dropped from the record).

## Step 2 — binding

`bind_experiment` re-enforces registration immutability/contamination at
measurement time. Any reject (`BindingNotFoundError` / `BindingRejectedError`)
is caught HERE — never left to propagate — and converted into an
UNDETERMINED outcome carrying the binding reason code(s), with the evidence
bundle still sealed (registration + a `missingness_report` entry noting what
binding could not admit).

## Step 3 — window

`confirmation.validate_confirmation` -> `clock.start_measurement_window` (or
`resolve_duplicate_window` on an idempotent replay) -> `window.
window_complete(evaluation_at)`. Any `Rejected`/`Undetermined`/incomplete
outcome here is UNDETERMINED with the matching reason code(s); the pipeline
NEVER fabricates a confirmed/complete window to keep going.

## Step 4 — DiD per signal

Runs unconditionally over `inputs.signals` (even when window/binding already
forced UNDETERMINED) so the evidence bundle can carry real `did_inputs`/
`did_outputs` entries and an honest DiD-insufficiency reason surfaces even
when it was not the FIRST problem found — this pipeline reports every
problem it discovers, not just the first.

## Step 5 — B-gate

`decide_b_verdict` folds ALL upstream problems (window incomplete/unconfirmed/
late, binding contamination, DiD insufficiency-derived flags, evidence
integrity) into its `WindowState`/`EvidenceCheck` inputs, so a single call
produces the authoritative verdict — this orchestrator does not layer its own
parallel verdict logic on top.

## Step 6 — evidence bundle

Always sealed, exactly once, over whatever entries the run actually produced
(registration/deployment_confirmation/observations/did_inputs/did_outputs/
b_gate_decision/grs_policy — `EvidenceKind` per `evidence.py`), PLUS a
`missingness_report` entry whenever any required kind could not be
constructed (an honest partial bundle, never a silently-complete one).
`verify_manifest` is asserted immediately after sealing (round-trip check) —
a seal that does not verify is a `PipelineError` (a genuine programmer-error
condition, not a measurement outcome).

## Step 7 — outcome record + atomic idempotent store

The `ExperimentOutcome` is built from the (possibly partial) results of steps
1-6, then wrapped in one `OutcomeDecisionRecord` (decision + evidence ref +
policy metadata, ATOMIC by construction per `ports.py`) and appended via
`OutcomeDecisionStore.append_decision`. A replay of the SAME inputs produces
a byte-identical `ExperimentOutcome.canonical_payload()` and therefore an
idempotent `PutOutcome.DUPLICATE` — never a second decision, never a
different one.
"""

from __future__ import annotations

from datetime import UTC, datetime

from saena_domain.audit.canonical import canonical_json, sha256_hex
from saena_domain.measurement import b_gate as b_gate_mod
from saena_domain.measurement import binding as binding_mod
from saena_domain.measurement import clock as clock_mod
from saena_domain.measurement import confirmation as confirmation_mod
from saena_domain.measurement import did as did_mod
from saena_domain.measurement import evidence as evidence_mod
from saena_domain.measurement import grs as grs_mod
from saena_domain.measurement.errors import IdempotencyConflictError
from saena_domain.measurement.outcome_layer import OutcomeLayer
from saena_domain.measurement.ports import (
    ConfirmationRecord,
    EvidenceBundle,
    OutcomeDecisionRecord,
    PutOutcome,
)
from saena_domain.measurement.ports import (
    MeasurementWindow as PortsMeasurementWindow,
)
from saena_domain.measurement.reason_codes import ReasonCode

from .errors import PipelineError
from .inputs import MeasurementInputs, MeasurementPolicies, MeasurementPorts
from .outcome import ExperimentOutcome, OutcomeStatus

_SHA256_PREFIX = "sha256:"

#: `evidence.EvidenceKind` values this orchestrator can, in principle, attach
#: — used only to build the `missingness_report` payload naming what was
#: skipped; the authoritative required set remains
#: `evidence.REQUIRED_B_GATE_KINDS`.
_ALL_TRACKED_KINDS = (
    evidence_mod.EvidenceKind.REGISTRATION,
    evidence_mod.EvidenceKind.DEPLOYMENT_CONFIRMATION,
    evidence_mod.EvidenceKind.BASELINE_OBSERVATION,
    evidence_mod.EvidenceKind.TREATMENT_OBSERVATION,
    evidence_mod.EvidenceKind.CONTROL_OBSERVATION,
    evidence_mod.EvidenceKind.RAW_OBSERVATION_REF,
    evidence_mod.EvidenceKind.DID_INPUTS,
    evidence_mod.EvidenceKind.DID_OUTPUTS,
    evidence_mod.EvidenceKind.B_GATE_DECISION,
    evidence_mod.EvidenceKind.GRS_POLICY,
)


def _hash_of(material: object) -> str:
    return f"{_SHA256_PREFIX}{sha256_hex(canonical_json(material))}"


def _evidence_ref(uri: str, material: object) -> evidence_mod.EvidenceRef:
    return evidence_mod.EvidenceRef(uri=uri, content_hash=_hash_of(material))


class _RunState:
    """Mutable per-call accumulator (local to one `run_measurement` call —
    never shared, never held across calls). Collects the reason codes and
    evidence entries every step contributes so the final assembly step (7)
    never has to re-derive anything a prior step already decided."""

    __slots__ = (
        "reason_codes",
        "entries",
        "present_kinds",
        "bound",
        "binding_failed",
        "window_failed",
        "confirmation_conflicted",
        "window",
        "did_result",
        "b_gate_decision",
        "grs_decision",
    )

    def __init__(self) -> None:
        self.reason_codes: set[ReasonCode] = set()
        self.entries: list[evidence_mod.EvidenceEntry] = []
        self.present_kinds: set[evidence_mod.EvidenceKind] = set()
        self.bound: binding_mod.BoundExperiment | None = None
        #: True iff step 2 (binding) rejected the submission — a fail-closed
        #: forcer on the FINAL status independent of whatever the B-gate
        #: computed from step 4/5 (see `_final_status`): a binding reject
        #: means the observations feeding DiD were never honestly admitted
        #: against the registration, so no verdict computed from them may
        #: ever be reported as PASS.
        self.binding_failed: bool = False
        #: True iff step 3 (confirmation/window) could not establish a
        #: started, complete window — same fail-closed-forcer role as
        #: `binding_failed` (see `_final_status`).
        self.window_failed: bool = False
        #: True iff persisting this run's deployment confirmation hit a
        #: same-tenant/same-key/DIFFERENT-content conflict in
        #: `ConfirmationStore` (`IdempotencyConflictError`): a first
        #: confirmation was already durably accepted under this idempotency
        #: key and this run presents contradictory content. The store, by
        #: contract, has NOT overwritten the first record. This run must not
        #: evaluate the conflicting confirmation as if it were accepted — the
        #: measurement steps are skipped entirely and the outcome is a
        #: fail-closed UNDETERMINED(conflicting_confirmation). Same
        #: fail-closed-forcer role as `binding_failed`/`window_failed`.
        self.confirmation_conflicted: bool = False
        self.window: clock_mod.MeasurementWindow | None = None
        self.did_result: did_mod.DiDResult | None = None
        self.b_gate_decision: b_gate_mod.BGateDecision | None = None
        self.grs_decision: grs_mod.GrsDecision | None = None

    def add_entry(self, entry: evidence_mod.EvidenceEntry) -> None:
        self.entries.append(entry)
        self.present_kinds.add(entry.kind)


# --------------------------------------------------------------------------
# Step 1 — GRS eligibility (first, honest, never blocking)
# --------------------------------------------------------------------------


def _run_grs(inputs: MeasurementInputs, policies: MeasurementPolicies, state: _RunState) -> None:
    decision = grs_mod.evaluate_grs_eligibility(inputs.grs_inputs, bundle=policies.grs_bundle)
    state.grs_decision = decision
    if decision.decision is not grs_mod.GrsEligibility.ELIGIBLE:
        state.reason_codes.add(ReasonCode.GRS_POLICY_MISSING)
    policy_material = {
        "decision": decision.decision.value,
        "reason": decision.reason,
        "policy_version": decision.policy_version,
        "bundle_hash": decision.bundle_hash,
        "provenance": decision.provenance.value if decision.provenance is not None else None,
        "is_production_valid": decision.is_production_valid,
    }
    state.add_entry(
        evidence_mod.EvidenceEntry(
            kind=evidence_mod.EvidenceKind.GRS_POLICY,
            ref=_evidence_ref("grs://policy-decision", policy_material),
            metadata=evidence_mod.EvidenceMetadata(
                extra={"decision": decision.decision.value},
            ),
        )
    )


# --------------------------------------------------------------------------
# Step 2 — binding
# --------------------------------------------------------------------------


def _run_binding(
    inputs: MeasurementInputs, policies: MeasurementPolicies, state: _RunState
) -> None:
    try:
        bound = binding_mod.bind_experiment(
            inputs.registration,
            inputs.submission,
            weights=policies.weights,
        )
    except binding_mod.BindingNotFoundError:
        state.reason_codes.add(ReasonCode.IDENTITY_MISMATCH)
        state.binding_failed = True
        return
    except binding_mod.BindingRejectedError as exc:
        _BINDING_REASON_MAP_STRICT = {
            "post_registration_mutation": ReasonCode.POST_REGISTRATION_METRIC_MUTATION,
            "conflicting_registration": ReasonCode.POST_REGISTRATION_METRIC_MUTATION,
            "metric_mutation": ReasonCode.POST_REGISTRATION_METRIC_MUTATION,
            "cell_mismatch": ReasonCode.CELL_MISMATCH,
            "contamination": ReasonCode.TREATMENT_CONTROL_CONTAMINATION,
            "asset_hash_conflict": ReasonCode.ASSET_HASH_CONFLICT,
        }
        state.reason_codes.add(_BINDING_REASON_MAP_STRICT[exc.reason])
        state.binding_failed = True
        return

    state.bound = bound
    state.add_entry(
        evidence_mod.EvidenceEntry(
            kind=evidence_mod.EvidenceKind.REGISTRATION,
            ref=_evidence_ref(
                f"registration://{bound.experiment_id}",
                {"experiment_id": bound.experiment_id, "anchored_hash": bound.anchored_hash},
            ),
        )
    )


# --------------------------------------------------------------------------
# Step 3 — deployment confirmation + window
# --------------------------------------------------------------------------


def _run_window(inputs: MeasurementInputs, policies: MeasurementPolicies, state: _RunState) -> None:
    verdict = confirmation_mod.validate_confirmation(
        inputs.deployment_confirmation,
        inputs.registration_view,
        inputs.server_received_at,
        policies.trust_verifier,
        inputs.prior_confirmations,
        policies.allowed_confirmation_skew_seconds,
    )

    if isinstance(verdict, confirmation_mod.Rejected):
        _CONFIRMATION_REASON_MAP = {
            confirmation_mod.RejectionReason.CROSS_TENANT_REPLAY: ReasonCode.IDENTITY_MISMATCH,
            confirmation_mod.RejectionReason.IDENTITY_MISMATCH: ReasonCode.IDENTITY_MISMATCH,
            confirmation_mod.RejectionReason.MISSING_DEPLOY_ARTIFACT: (
                ReasonCode.DEPLOYMENT_UNCONFIRMED
            ),
            confirmation_mod.RejectionReason.MISSING_DEPLOYMENT_TARGET: (
                ReasonCode.DEPLOYMENT_UNCONFIRMED
            ),
            confirmation_mod.RejectionReason.UNTRUSTED_CONFIRMER: (
                ReasonCode.DEPLOYMENT_UNCONFIRMED
            ),
            confirmation_mod.RejectionReason.CONFIRMER_VERIFICATION_FAILED: (
                ReasonCode.DEPLOYMENT_UNCONFIRMED
            ),
            confirmation_mod.RejectionReason.BACKDATED_CONFIRMATION: (
                ReasonCode.DEPLOYMENT_UNCONFIRMED
            ),
            confirmation_mod.RejectionReason.FUTURE_CONFIRMATION: (
                ReasonCode.DEPLOYMENT_UNCONFIRMED
            ),
            confirmation_mod.RejectionReason.CONFLICTING_REPLAY: (
                ReasonCode.CONFLICTING_CONFIRMATION
            ),
            confirmation_mod.RejectionReason.UNKNOWN_REGISTRATION: (
                ReasonCode.DEPLOYMENT_UNCONFIRMED
            ),
            confirmation_mod.RejectionReason.NAIVE_TIMESTAMP: ReasonCode.DEPLOYMENT_UNCONFIRMED,
        }
        state.reason_codes.add(_CONFIRMATION_REASON_MAP[verdict.reason_code])
        state.window_failed = True
        return

    accepted = verdict.accepted if isinstance(verdict, confirmation_mod.Duplicate) else verdict

    clock_verdict = clock_mod.start_measurement_window(
        accepted, inputs.registration_view, policies.clock_policy
    )
    if isinstance(clock_verdict, clock_mod.Undetermined):
        state.reason_codes.add(ReasonCode.DEPLOYMENT_LATE)
        state.window_failed = True
        state.add_entry(
            evidence_mod.EvidenceEntry(
                kind=evidence_mod.EvidenceKind.DEPLOYMENT_CONFIRMATION,
                ref=_evidence_ref(
                    f"confirmation://{accepted.confirmation.idempotency_key}",
                    {
                        "idempotency_key": accepted.confirmation.idempotency_key,
                        "clock_start": "deployment_late",
                    },
                ),
            )
        )
        return

    window = clock_verdict
    state.window = window
    state.add_entry(
        evidence_mod.EvidenceEntry(
            kind=evidence_mod.EvidenceKind.DEPLOYMENT_CONFIRMATION,
            ref=_evidence_ref(
                f"confirmation://{accepted.confirmation.idempotency_key}",
                {
                    "idempotency_key": accepted.confirmation.idempotency_key,
                    "anchor": window.anchor.isoformat(),
                    "end": window.end.isoformat(),
                },
            ),
        )
    )
    if not window.window_complete(inputs.evaluation_at):
        state.reason_codes.add(ReasonCode.WINDOW_INCOMPLETE)
        state.window_failed = True


# --------------------------------------------------------------------------
# Step 4 — DiD per signal
# --------------------------------------------------------------------------

_OBSERVATION_KIND_BY_LAYER_SLOT = {
    "baseline_treatment": evidence_mod.EvidenceKind.BASELINE_OBSERVATION,
    "post_treatment": evidence_mod.EvidenceKind.TREATMENT_OBSERVATION,
    "baseline_control": evidence_mod.EvidenceKind.BASELINE_OBSERVATION,
    "post_control": evidence_mod.EvidenceKind.CONTROL_OBSERVATION,
}


def _run_did(inputs: MeasurementInputs, policies: MeasurementPolicies, state: _RunState) -> None:
    # `window_start` is deliberately left `None`: baseline observations are
    # captured BEFORE the 7-day post-deployment window opens (Day 0, by
    # design — see wave5-plan.md deliverable 1/Algorithm §3.7), so bounding
    # baseline cells by the window's start would misclassify every honest
    # baseline repeat as "late". Only `window_end` gates lateness here — a
    # POST-period repeat observed after the window closes is late (Algorithm
    # §7.3's causality contract); a PRE-period (baseline) repeat is never
    # subject to the post-window bound.
    window = state.window
    window_end = window.end if window is not None else None

    did_result = did_mod.compute_did(
        inputs.signals,
        policies.did_policy,
        window_start=None,
        window_end=window_end,
    )
    state.did_result = did_result

    state.add_entry(
        evidence_mod.EvidenceEntry(
            kind=evidence_mod.EvidenceKind.DID_INPUTS,
            ref=_evidence_ref(
                "did://inputs",
                [
                    {
                        "layer": s.layer,
                        "metric_id": s.metric_id,
                        "evidence_basis_id": s.evidence_basis_id,
                    }
                    for s in inputs.signals
                ],
            ),
        )
    )
    state.add_entry(
        evidence_mod.EvidenceEntry(
            kind=evidence_mod.EvidenceKind.DID_OUTPUTS,
            ref=_evidence_ref("did://outputs", did_result.canonical_json()),
        )
    )

    # Raw observation refs — one entry per non-empty cell across all signals,
    # each carrying whatever caller-supplied EvidenceMetadata (timestamp /
    # client_version / asset_hash / citation decision) is available for it.
    # Presence of AT LEAST ONE such ref is what makes `RAW_OBSERVATION_REF`
    # satisfiable; observation-KIND entries (baseline/treatment/control) are
    # emitted per populated cell.
    metadata_by_kind: dict[evidence_mod.EvidenceKind, dict[str, evidence_mod.EvidenceMetadata]] = {
        evidence_mod.EvidenceKind.BASELINE_OBSERVATION: dict(inputs.baseline_evidence),
        evidence_mod.EvidenceKind.TREATMENT_OBSERVATION: dict(inputs.treatment_evidence),
        evidence_mod.EvidenceKind.CONTROL_OBSERVATION: dict(inputs.control_evidence),
    }
    any_raw_ref = False
    for series in inputs.signals:
        for slot, kind in _OBSERVATION_KIND_BY_LAYER_SLOT.items():
            cell = getattr(series, slot)
            if cell is None:
                continue
            metadata = metadata_by_kind[kind].get(series.evidence_basis_id)
            if metadata is None:
                # Honest fallback: caller supplied no per-observation
                # provenance for this basis. Observation-kind entries REQUIRE
                # full provenance (evidence.py `_check_observation_provenance`)
                # so without it we cannot honestly construct this entry — the
                # gap surfaces via `validate_completeness`/`missingness_report`
                # rather than a synthesized/forged metadata value.
                continue
            state.add_entry(
                evidence_mod.EvidenceEntry(
                    kind=kind,
                    ref=_evidence_ref(
                        f"observation://{series.evidence_basis_id}/{slot}",
                        {"evidence_basis_id": series.evidence_basis_id, "slot": slot},
                    ),
                    metadata=metadata,
                )
            )
            any_raw_ref = True

    if any_raw_ref:
        state.add_entry(
            evidence_mod.EvidenceEntry(
                kind=evidence_mod.EvidenceKind.RAW_OBSERVATION_REF,
                ref=_evidence_ref(
                    "raw-observation-ref://summary",
                    sorted({s.evidence_basis_id for s in inputs.signals}),
                ),
            )
        )


# --------------------------------------------------------------------------
# Step 5 — B-gate
# --------------------------------------------------------------------------


def _signal_result(signal: did_mod.SignalDiD) -> b_gate_mod.SignalResult | None:
    """Map one `SignalDiD` onto a `b_gate.SignalResult`, or `None` if the
    signal's `layer` is not a valid `OutcomeLayer` (e.g. a DiD signal fed by
    an upstream producer using a layer name outside the closed B-layer
    vocabulary) — such a signal cannot be scored by the gate at all and is
    surfaced via `OBSERVATION_ADAPTER_DRIFT` instead of raising."""
    try:
        layer = OutcomeLayer(signal.layer)
    except ValueError:
        return None
    treatment_raw = signal.treatment_raw_delta if signal.treatment_raw_delta is not None else 0.0
    control_raw = signal.control_raw_delta if signal.control_raw_delta is not None else 0.0
    has_lift = signal.net_of_control_lift is not None
    net_lift = signal.net_of_control_lift if signal.net_of_control_lift is not None else 0.0
    return b_gate_mod.SignalResult(
        layer=layer,
        evidence_basis_id=signal.evidence_basis_id,
        treatment_raw_delta=treatment_raw,
        control_raw_delta=control_raw,
        net_of_control_lift=net_lift,
        has_control_adjusted_lift=has_lift,
        sufficient_data=not signal.insufficient,
        has_raw_evidence_ref=True,
    )


def _run_b_gate(inputs: MeasurementInputs, policies: MeasurementPolicies, state: _RunState) -> None:
    did_result = state.did_result
    signal_results: list[b_gate_mod.SignalResult] = []
    adapter_drift = False
    if did_result is not None:
        for signal in did_result.signals:
            mapped = _signal_result(signal)
            if mapped is None:
                adapter_drift = True
                continue
            signal_results.append(mapped)

    manifest_hash_ok = True  # verified post-seal in step 6; see assembly note
    raw_refs_present = evidence_mod.EvidenceKind.RAW_OBSERVATION_REF in state.present_kinds

    window_state = b_gate_mod.WindowState(
        complete=ReasonCode.WINDOW_INCOMPLETE not in state.reason_codes,
        deployment_confirmed=ReasonCode.DEPLOYMENT_UNCONFIRMED not in state.reason_codes
        and ReasonCode.DEPLOYMENT_LATE not in state.reason_codes,
        deployment_late=ReasonCode.DEPLOYMENT_LATE in state.reason_codes,
        contamination=ReasonCode.TREATMENT_CONTROL_CONTAMINATION in state.reason_codes,
        adapter_drift=adapter_drift,
        missing_baseline=any(
            did_mod.InsufficiencyCode.MISSING_BASELINE in s.insufficiency_codes
            for s in (did_result.signals if did_result is not None else ())
        ),
        missing_control=any(
            did_mod.InsufficiencyCode.MISSING_CONTROL in s.insufficiency_codes
            for s in (did_result.signals if did_result is not None else ())
        ),
        insufficient_repeats=any(
            did_mod.InsufficiencyCode.INSUFFICIENT_REPEATS in s.insufficiency_codes
            for s in (did_result.signals if did_result is not None else ())
        ),
    )
    evidence_check = b_gate_mod.EvidenceCheck(
        manifest_hash_ok=manifest_hash_ok,
        raw_refs_present=raw_refs_present,
    )

    decision = b_gate_mod.decide_b_verdict(
        tuple(signal_results), evidence_check, window_state, policies.gate_policy
    )
    state.b_gate_decision = decision
    state.reason_codes.update(decision.reason_codes)

    state.add_entry(
        evidence_mod.EvidenceEntry(
            kind=evidence_mod.EvidenceKind.B_GATE_DECISION,
            ref=_evidence_ref(
                "b-gate://decision",
                {
                    "verdict": decision.verdict.value,
                    "reason_codes": [c.value for c in decision.reason_codes],
                    "qualifying_layers": [layer.value for layer in decision.qualifying_layers],
                },
            ),
        )
    )


# --------------------------------------------------------------------------
# Step 6 — evidence bundle seal
# --------------------------------------------------------------------------


def _seal_bundle(
    inputs: MeasurementInputs, state: _RunState
) -> tuple[evidence_mod.EvidenceBundleManifest, bool]:
    is_complete, missing = evidence_mod.validate_completeness(
        evidence_mod.EvidenceBundleManifest.seal(
            tenant_id=inputs.tenant_id,
            run_id=inputs.run_id,
            experiment_id=inputs.experiment_id,
            entries=tuple(state.entries),
        )
    )
    entries = list(state.entries)
    if not is_complete:
        entries.append(
            evidence_mod.EvidenceEntry(
                kind=evidence_mod.EvidenceKind.MISSINGNESS_REPORT,
                ref=_evidence_ref(
                    "missingness-report://gaps",
                    sorted(kind.value for kind in missing),
                ),
                metadata=evidence_mod.EvidenceMetadata(
                    extra={"missing_kinds": sorted(kind.value for kind in missing)}
                ),
            )
        )

    manifest = evidence_mod.EvidenceBundleManifest.seal(
        tenant_id=inputs.tenant_id,
        run_id=inputs.run_id,
        experiment_id=inputs.experiment_id,
        entries=tuple(entries),
    )
    ok, _divergence_index = evidence_mod.verify_manifest(manifest)
    if not ok:
        raise PipelineError(
            "sealed evidence bundle failed its own round-trip verification "
            "(programmer-error condition, not a measurement outcome)",
            context={"tenant_id": inputs.tenant_id, "experiment_id": inputs.experiment_id},
        )
    return manifest, is_complete


# --------------------------------------------------------------------------
# Step 7 — outcome record + atomic idempotent store
# --------------------------------------------------------------------------


def _final_status(state: _RunState) -> OutcomeStatus:
    """The ONE place a `BVerdict` becomes the outcome's `status`.

    Three independent fail-closed forcers can each demote an otherwise-PASS
    B-gate verdict down to UNDETERMINED — none of them can ever PROMOTE a
    status, only hold it back:

    - GRS non-eligibility (wave5-plan.md directive: "GRS ... no bundle ->
      UNDETERMINED ... never PASS").
    - `state.binding_failed` — step 2 rejected the measurement submission
      against its registration (post-registration mutation, contamination,
      cell mismatch, cross-tenant/not-found, ...). A verdict computed from
      observations that were never honestly admitted must never be reported
      as PASS, no matter what the B-gate mechanically computed from whatever
      signals happened to be supplied alongside the rejected submission.
    - `state.window_failed` — step 3 could not establish a confirmed,
      complete measurement window (rejected confirmation, Day-2 late
      deployment, or window not yet elapsed). `decide_b_verdict` already
      folds most of this into its OWN `WindowState` (see `_run_b_gate`), but
      this is a defence-in-depth belt: a window failure this orchestrator
      recorded for a reason the B-gate's `WindowState` mapping did not
      explicitly cover (e.g. a rejected confirmation before any window could
      even be attempted) must still demote a stray PASS.

    A `None` B-gate decision (should not occur — `_run_b_gate` always runs
    and always returns a decision — defensive only) is UNDETERMINED.
    """
    decision = state.b_gate_decision
    grs_ok = (
        state.grs_decision is not None
        and state.grs_decision.decision is grs_mod.GrsEligibility.ELIGIBLE
    )
    # A conflicting confirmation short-circuits before `_run_b_gate`, so
    # `decision` is None on that path and the guard below already yields
    # UNDETERMINED; this explicit check is a defence-in-depth belt so the
    # forcer holds even if the short-circuit is ever refactored away.
    if state.confirmation_conflicted:
        return OutcomeStatus.UNDETERMINED
    if decision is None:
        return OutcomeStatus.UNDETERMINED
    status = OutcomeStatus.from_b_verdict(decision.verdict)
    if status is OutcomeStatus.PASS and (not grs_ok or state.binding_failed or state.window_failed):
        return OutcomeStatus.UNDETERMINED
    return status


def run_measurement(
    inputs: MeasurementInputs,
    ports: MeasurementPorts,
    policies: MeasurementPolicies,
) -> ExperimentOutcome:
    """Run the full fail-closed measurement pipeline for ONE experiment run.

    Pure composition over `saena_domain.measurement.*` plus the injected
    `ports`/`policies` — see module docstring for the full step-by-step
    contract. ALWAYS returns an `ExperimentOutcome`; the only exception this
    function raises is `PipelineError`, and only for a genuine
    programmer-error / integrity-violation condition (an evidence bundle that
    fails its own round-trip verification, or a store that reports something
    other than STORED/DUPLICATE) — never for a fail-closed measurement
    condition, which is always represented in the returned record's `status`
    + `reason_codes` instead.

    Idempotent: calling this twice with byte-identical `inputs`/`policies`
    (and a `ports.decision_store` that already holds the first call's
    decision) returns an `ExperimentOutcome` whose `canonical_payload()` is
    byte-identical to the first call's, and the SECOND `append_decision` call
    resolves to `PutOutcome.DUPLICATE` — no second decision is ever recorded.
    """
    state = _RunState()

    # Persist the confirmation submission itself first (idempotent — this is
    # the record `ConfirmationStore` durably remembers this run's confirmation
    # attempt under). Uses the confirmation's own idempotency_key.
    #
    # A same-tenant/same-key/different-content conflict (`IdempotencyConflict
    # Error`) is an EXPECTED fail-closed measurement condition, NOT a
    # programmer error: a first confirmation was already durably accepted
    # under this key and this run presents contradictory content. The store,
    # by contract, has already refused to overwrite the first record. We must
    # NOT evaluate the conflicting confirmation as if accepted, so we skip
    # every measurement step and fall straight through to a fail-closed
    # UNDETERMINED(conflicting_confirmation) outcome. This is caught narrowly
    # by exception TYPE — any other error (integrity, programmer, unexpected
    # store disposition) still propagates as its own typed error. Byte-
    # identical replay does NOT raise (the store returns DUPLICATE) and takes
    # the normal path below, preserving idempotency.
    try:
        ports.confirmation_store.put_confirmation(
            inputs.tenant_id,
            inputs.deployment_confirmation.idempotency_key,
            ConfirmationRecord(
                tenant_id=inputs.tenant_id,
                confirmation_key=inputs.deployment_confirmation.idempotency_key,
                measurement_kind="deployment_confirmation",
                payload=inputs.deployment_confirmation.model_dump(mode="json"),
            ),
        )
    except IdempotencyConflictError:
        state.confirmation_conflicted = True
        state.reason_codes.add(ReasonCode.CONFLICTING_CONFIRMATION)

    if not state.confirmation_conflicted:
        _run_grs(inputs, policies, state)
        _run_binding(inputs, policies, state)
        _run_window(inputs, policies, state)
        _run_did(inputs, policies, state)
        _run_b_gate(inputs, policies, state)

    manifest, is_complete = _seal_bundle(inputs, state)

    if state.window is not None and manifest.manifest_hash is not None:
        ports.window_store.open_window(
            inputs.tenant_id,
            _measurement_window_record(inputs, state.window, policies),
        )

    status = _final_status(state)
    decision = state.b_gate_decision
    grs_decision = state.grs_decision

    outcome = ExperimentOutcome(
        tenant_id=inputs.tenant_id,
        run_id=inputs.run_id,
        experiment_id=inputs.experiment_id,
        status=status,
        reason_codes=tuple(sorted(state.reason_codes, key=lambda c: c.value)),
        qualifying_layers=tuple(
            layer.value for layer in (decision.qualifying_layers if decision else ())
        ),
        raw_view=tuple(layer.value for layer in (decision.raw_view if decision else ())),
        control_adjusted_view=tuple(
            layer.value for layer in (decision.control_adjusted_view if decision else ())
        ),
        b_gate_decision=decision,
        grs_decision=grs_decision,
        evidence_bundle_ref=manifest.manifest_hash,
        evidence_bundle_complete=is_complete,
        policy_version=policies.gate_policy.version,
        policy_hash=policies.gate_policy.hash,
        is_production=bool(decision.is_production) if decision is not None else False,
        computed_at=_deterministic_computed_at(inputs),
    )

    ports.evidence_store.put(
        inputs.tenant_id,
        manifest.manifest_hash or _hash_of({"empty": True}),
        EvidenceBundle(tenant_id=inputs.tenant_id, manifest=manifest.model_dump(mode="json")),
    )

    decision_key = (inputs.experiment_id, inputs.run_id)
    put_result = ports.decision_store.append_decision(
        inputs.tenant_id,
        OutcomeDecisionRecord(
            tenant_id=inputs.tenant_id,
            decision_key=decision_key,
            outcome=outcome.status.value,
            evidence_bundle_ref=manifest.manifest_hash or _hash_of({"empty": True}),
            policy_metadata=outcome.canonical_payload(),
        ),
    )
    if put_result.outcome not in (PutOutcome.STORED, PutOutcome.DUPLICATE):
        raise PipelineError(  # pragma: no cover - defensive; ports never return anything else
            "outcome decision store returned neither STORED nor DUPLICATE",
            context={"tenant_id": inputs.tenant_id, "experiment_id": inputs.experiment_id},
        )

    return outcome


def _measurement_window_record(
    inputs: MeasurementInputs,
    window: clock_mod.MeasurementWindow,
    policies: MeasurementPolicies,
) -> PortsMeasurementWindow:
    return PortsMeasurementWindow(
        tenant_id=inputs.tenant_id,
        experiment_id=inputs.experiment_id,
        starts_at=window.anchor.isoformat(),
        ends_at=window.end.isoformat(),
        policy_version=f"{policies.clock_policy.window_days}d",
    )


def _deterministic_computed_at(inputs: MeasurementInputs) -> datetime:
    """The outcome record's `computed_at` — deterministic per this run's
    inputs (NOT `datetime.now()`), so replaying identical inputs yields a
    byte-identical `ExperimentOutcome.canonical_payload()`. Uses
    `evaluation_at` (the instant the caller asked the pipeline to evaluate
    against — Temporal workflow-time in production) directly: it is already
    part of `inputs`, already UTC-aware by construction of
    `MeasurementWindow.window_complete`'s own requirement, and reusing it
    (rather than a wall-clock read) is what keeps this function pure."""
    at = inputs.evaluation_at
    if at.tzinfo is None:
        return at.replace(tzinfo=UTC)
    return at


__all__ = ["run_measurement"]

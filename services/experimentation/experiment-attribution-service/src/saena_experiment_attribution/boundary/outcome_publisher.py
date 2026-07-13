"""`OutcomePublisher` — assembles + fail-closed-gates `experiment.outcome.observed.v1`
(w5-12).

Maps a `BGateDecision` (w5-06) + `DiDResult` (w5-05) + an evidence-bundle
`manifest_hash` (w5-08) into an `experiment.outcome.observed.v1` payload,
validates the assembly against the generated `saena_schemas` model, and
enforces the engine-scope + policy-gate obligations CLAUDE.md and
wave5-plan.md assign to this boundary.

## Why the schema alone cannot enforce these invariants

`ExperimentOutcomeObservedV1Payload` (like `DeploymentConfirmedV1Payload`) is
`extra="allow"` (open-class payload contract, wave5-plan.md "outcome-field-gap"
carried obligation: "open-class payloads cannot schema-reject stray
`lift`/`outcome`; W5 closes via policy-gate/guard obligation honestly
(w5-06/w5-12), not silently"). A `BGateDecision` is ALSO, by its own
docstring, "not self-authenticating": any code can construct one, including a
forged one via `model_construct` that bypasses pydantic validation entirely
(`b_gate.py` module docstring, "BGateDecision is not self-authenticating").
Neither the JSON Schema nor the domain model can therefore be the sole gate
on a `b_verdict == "pass"` publish — this class is the fail-closed guard that
sits at the trust boundary where a decision object crosses from "something
any code constructed" into "something republished as an authoritative
external-facing event".

## Fail-closed policy-gate obligation (critical guard)

`publish` REFUSES (raises `PublishRefusedError`, publishes NOTHING — never a
downgraded/partial payload) when `decision.verdict is BVerdict.PASS` UNLESS
ALL of:

(a) `len(decision.qualifying_layers) >= b_gate.MIN_INDEPENDENT_LAYERS` (≥2
    qualifying layers) — re-derived from the SAME field the B-gate itself
    populates (`BGateDecision.qualifying_layers`), defensively re-checked
    here rather than trusted blindly, because (per the module docstring
    above) the decision object crossing this boundary might not have come
    from a real call to `decide_b_verdict` at all.
(b) The evidence manifest resolved via `ManifestLookup` verifies:
    `saena_domain.measurement.evidence.verify_manifest(manifest) ==
    (True, None)` — this is the w5-08 SF-4 obligation, re-run AT THIS TRUST
    BOUNDARY rather than trusting an upstream "it was verified once"
    claim. A manifest that fails to resolve (`ManifestLookup` returns
    `None`) is treated identically to a manifest that fails verification —
    both refuse the publish.
(c) `decision.policy_provenance` is `PolicyProvenance.PRODUCTION` or
    `PolicyProvenance.TEST_FIXTURE` — i.e. `decision.policy_provenance` IS
    (by construction of the closed `PolicyProvenance` enum) one of exactly
    those two values; the check here re-validates it against the closed
    enum defensively (a `model_construct`-bypassed decision could carry an
    enum member value that was never actually validated as a member,
    depending on how the bypass was performed) and additionally requires
    `decision.is_production` to agree with `decision.policy_provenance`
    (an internally-inconsistent decision — `is_production=True` paired with
    `policy_provenance=TEST_FIXTURE` or vice versa — is refused as a
    forged/corrupted decision, never trusted on either field alone).

Every one of (a)/(b)/(c) is independently checked and ALL unmet reasons are
collected into `PublishRefusedError.context["reasons"]` — a caller sees every
unmet condition, not just the first (so a guard-mutation test removing any
one of the three checks flips at least one assertion, per wave5-plan.md's
"guard mutation" discipline).

A `b_verdict` of `FAIL` or `UNDETERMINED` carries NO such gate — those
verdicts are never a claim of external success, so there is nothing to
protect against (they publish immediately once engine/schema checks pass).

## Engine-scope guard

CLAUDE.md "Engine scope (v1)": Target = ChatGPT Search only. `publish`
refuses (fail-closed) any `engine_id` other than the single permitted value
`"chatgpt-search"` — mirrors `saena_domain.events.factory`'s
`EngineNotPermittedError` guard, re-derived here because this boundary
assembles the payload itself rather than receiving one already validated by
`EnvelopeFactory`.
"""

from __future__ import annotations

from pydantic import ValidationError
from saena_domain.measurement.b_gate import (
    MIN_INDEPENDENT_LAYERS,
    BGateDecision,
    BVerdict,
    PolicyProvenance,
)
from saena_domain.measurement.did import DiDResult, SignalDiD
from saena_domain.measurement.evidence import verify_manifest
from saena_schemas.event.experiment_outcome_observed_v1 import (
    BVerdict as WireVerdict,
)
from saena_schemas.event.experiment_outcome_observed_v1 import (
    EvidenceBundleRef,
    ExperimentOutcomeObservedV1Payload,
    GrsPolicy,
    PerSignalResult,
    SampleCounts,
    Window,
)
from saena_schemas.event.experiment_outcome_observed_v1 import (
    FieldModel as EngineIdField,
)
from saena_schemas.event.experiment_outcome_observed_v1 import (
    ReasonCode as WireReasonCode,
)

from .errors import EngineNotPermittedError, PayloadValidationError, PublishRefusedError
from .ports import ManifestLookup

#: v1 closed engine-scope vocabulary (CLAUDE.md "Engine scope (v1)").
_PERMITTED_ENGINE_ID = "chatgpt-search"

#: Production-or-explicitly-test provenance values a publishable decision
#: must carry (deliverable #2b condition c).
_ALLOWED_PROVENANCE = frozenset({PolicyProvenance.PRODUCTION, PolicyProvenance.TEST_FIXTURE})


def _sample_counts_for(signal: SignalDiD) -> SampleCounts:
    treatment = signal.sample_counts.get("post_treatment", 0)
    control = signal.sample_counts.get("post_control", 0)
    return SampleCounts(treatment=treatment, control=control)


class OutcomePublisher:
    """Assembles + fail-closed-gates an `experiment.outcome.observed.v1` payload.

    `manifest_lookup` is injected (no real DB) — see `ports.ManifestLookup`.
    """

    def __init__(self, *, manifest_lookup: ManifestLookup) -> None:
        self._manifest_lookup = manifest_lookup

    def publish(
        self,
        *,
        tenant_id: str,
        engine_id: str,
        experiment_id: str,
        registration_canonical_hash: str,
        deployment_confirmation_ref: str,
        window: Window,
        did_result: DiDResult,
        decision: BGateDecision,
        manifest_hash: str,
        artifact_ref: str,
        grs_policy: GrsPolicy,
    ) -> dict[str, object]:
        """Return the assembled + validated payload dict, or raise.

        Raises `EngineNotPermittedError` for any `engine_id` other than
        `"chatgpt-search"`. Raises `PublishRefusedError` (fail-closed —
        NOTHING is published) when `decision.verdict is BVerdict.PASS` and
        any of the three policy-gate conditions is unmet. Raises
        `PayloadValidationError` if the assembled payload does not conform
        to the `experiment.outcome.observed.v1` contract (a defensive
        double-check — this should not normally trigger given the typed
        inputs, but a `model_construct`-forged `decision`/`did_result` could
        smuggle a non-finite or otherwise invalid value through).
        """
        self._check_engine_id(engine_id)
        if decision.verdict is BVerdict.PASS:
            self._enforce_pass_policy_gate(
                tenant_id=tenant_id, decision=decision, manifest_hash=manifest_hash
            )

        per_signal_results = [self._per_signal_result(signal) for signal in did_result.signals]
        payload = ExperimentOutcomeObservedV1Payload(
            engine_id=EngineIdField(engine_id),
            experiment_id=experiment_id,
            registration_canonical_hash=registration_canonical_hash,  # type: ignore[arg-type]
            window=window,
            deployment_confirmation_ref=deployment_confirmation_ref,
            per_signal_results=per_signal_results,
            b_verdict=_to_wire_verdict(decision.verdict),
            reason_codes=[WireReasonCode(code.value) for code in decision.reason_codes] or None,
            raw_view={"layers": [layer.value for layer in decision.raw_view]},
            control_adjusted_view={
                "layers": [layer.value for layer in decision.control_adjusted_view]
            },
            confidence=decision.confidence,
            evidence_bundle_ref=EvidenceBundleRef(
                manifest_hash=manifest_hash,  # type: ignore[arg-type]
                artifact_ref=artifact_ref,  # type: ignore[arg-type]
            ),
            grs_policy=grs_policy,
        )
        return self._revalidate(payload)

    def _check_engine_id(self, engine_id: str) -> None:
        if engine_id != _PERMITTED_ENGINE_ID:
            raise EngineNotPermittedError(
                f"engine_id {engine_id!r} is not permitted — v1 scope is "
                f"{_PERMITTED_ENGINE_ID!r} only",
                context={"engine_id": engine_id},
            )

    def _enforce_pass_policy_gate(
        self, *, tenant_id: str, decision: BGateDecision, manifest_hash: str
    ) -> None:
        reasons: list[str] = []

        if len(decision.qualifying_layers) < MIN_INDEPENDENT_LAYERS:
            reasons.append("insufficient_qualifying_layers")

        manifest = self._manifest_lookup.lookup(tenant_id, manifest_hash)
        if manifest is None:
            reasons.append("evidence_manifest_unresolved")
        else:
            verified, _divergence_index = verify_manifest(manifest)
            if not verified:
                reasons.append("evidence_manifest_unverified")

        provenance_ok = decision.policy_provenance in _ALLOWED_PROVENANCE
        production_flag_consistent = decision.is_production == (
            decision.policy_provenance is PolicyProvenance.PRODUCTION
        )
        if not provenance_ok or not production_flag_consistent:
            reasons.append("policy_provenance_not_production_or_test")

        if reasons:
            raise PublishRefusedError(
                "refusing to publish a b_verdict=pass outcome — fail-closed "
                "policy-gate obligation not satisfied",
                context={"reasons": reasons, "tenant_id": tenant_id},
            )

    @staticmethod
    def _per_signal_result(signal: SignalDiD) -> PerSignalResult:
        return PerSignalResult(
            outcome_layer=signal.layer,  # type: ignore[arg-type]
            metric_id=signal.metric_id,
            evidence_basis_id=signal.evidence_basis_id,
            treatment_raw_delta=signal.treatment_raw_delta or 0.0,
            control_raw_delta=signal.control_raw_delta or 0.0,
            net_of_control_lift=signal.net_of_control_lift or 0.0,
            sample_counts=_sample_counts_for(signal),
            insufficient=signal.insufficient,
        )

    @staticmethod
    def _revalidate(payload: ExperimentOutcomeObservedV1Payload) -> dict[str, object]:
        as_dict = payload.model_dump(mode="json")
        try:
            ExperimentOutcomeObservedV1Payload.model_validate(as_dict)
        except ValidationError as exc:
            raise PayloadValidationError(
                "assembled experiment.outcome.observed.v1 payload failed "
                "re-validation against its own contract",
                context={"errors": exc.error_count()},
            ) from exc
        return as_dict


def _to_wire_verdict(verdict: BVerdict) -> WireVerdict:
    # BVerdict.PASS's wire value is "pass", a Python keyword — the generated
    # saena_schemas enum names that member `pass_`; both share the same
    # underlying string value ("pass"), which WireVerdict(...) resolves by
    # value, not by member name.
    return WireVerdict(verdict.value)


__all__ = ["OutcomePublisher"]

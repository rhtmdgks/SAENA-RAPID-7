"""Shared constants + builder helpers for the w5-19 measurement E2E (`tests/e2e/
measurement` + `tests/integration/measurement_e2e`).

Deliberately NOT named `conftest.py` — a second `conftest.py` in a sibling test
directory collides under pytest's default `prepend` import mode (see `tests/e2e/
intelligence/intelligence_e2e_harness.py`'s own docstring, which this module
mirrors convention-for-convention). This module has NO pytest fixtures of its
own — only plain constants and pure builder functions BOTH lanes (the
pure-synthetic `tests/e2e/measurement` lane and the real-container
`tests/integration/measurement_e2e` lane) import, so both lanes build from
byte-identical synthetic input.

Composed flow this package drives end-to-end, REAL components throughout (no
mock-only chain — every module below is the actual w5-02..w5-16 production
package, never a hand-rolled stand-in):

    experiment registration ledger (register)
      -> deployment.confirmed.v1-shaped confirmation -> Accepted
      -> saena_experiment_attribution.pipeline.run_measurement
         (binding -> window/clock -> DiD -> B-gate -> evidence-bundle seal ->
          OutcomeDecisionRecord append, via injected MeasurementPorts)
      -> saena_experiment_attribution.boundary.OutcomePublisher
         (assembles + fail-closed-gates experiment.outcome.observed.v1)
      -> saena_analytics_clickhouse MeasurementOutcomeRow projection
      -> saena_strategy_skill_bank.intake.IntakeGuard (B-verified-only)

Every step is deterministic (injected clock/ids, no wall-clock/random/network)
and tenant-scoped. `run_measurement` itself performs the ONLY "I/O" in the
pure-synthetic lane — writes through the injected `MeasurementPorts`, which are
the real in-memory reference adapters (`saena_domain.measurement.ports`) in the
pure lane and the REAL Postgres adapters (w5-10, via a sync facade mirroring
`tests/integration/measurement_pg/sync_facade.py`) in the container lane.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from saena_domain.experiment.ledger import register
from saena_domain.experiment.models import ExperimentArm, ExperimentRegistration, MetricDefinition
from saena_domain.measurement.b_gate import GatePolicy
from saena_domain.measurement.b_gate import PolicyProvenance as GatePolicyProvenance
from saena_domain.measurement.binding import (
    MeasurementCell,
    MeasurementMetricInput,
    MeasurementSubmission,
    Observation,
    WeightsPolicy,
    compute_metric_fingerprint,
)
from saena_domain.measurement.clock import MeasurementPolicy as ClockPolicy
from saena_domain.measurement.confirmation import (
    DeploymentConfirmation,
    RegistrationView,
    TrustVerifier,
    validate_confirmation,
)
from saena_domain.measurement.did import CellObservation, DiDPolicy, SignalSeries, compute_did
from saena_domain.measurement.evidence import EvidenceBundleManifest, EvidenceMetadata
from saena_domain.measurement.grs import GrsPolicyBundle, make_test_fixture_policy
from saena_domain.measurement.ports import (
    EvidenceBundleStore,
    InMemoryConfirmationStore,
    InMemoryEvidenceBundleStore,
    InMemoryMeasurementWindowStore,
    InMemoryOutcomeDecisionStore,
)
from saena_experiment_attribution.boundary.outcome_publisher import OutcomePublisher
from saena_experiment_attribution.pipeline.inputs import (
    MeasurementInputs,
    MeasurementPolicies,
    MeasurementPorts,
)
from saena_experiment_attribution.pipeline.orchestrator import run_measurement
from saena_experiment_attribution.pipeline.outcome import ExperimentOutcome, OutcomeStatus
from saena_schemas.event.experiment_outcome_observed_v1 import GrsPolicy as WireGrsPolicy
from saena_schemas.event.experiment_outcome_observed_v1 import Window as WirePayloadWindow
from saena_strategy_skill_bank.intake import (
    IntakeCandidate,
    IntakeDecision,
    IntakeGuard,
    SourceOutcomeAssertion,
    SourceOutcomeProvenance,
)

# ---------------------------------------------------------------------------
# Tenant / run identity — two tenants prove end-to-end isolation.
# ---------------------------------------------------------------------------

TENANT_1 = "w5e2e-tenant-one"
TENANT_2 = "w5e2e-tenant-two"
RUN_ID = "run-w5e2e-0001"
EXPERIMENT_ID = "exp-w5e2e-0001"
ENGINE_ID = "chatgpt-search"
METRIC_ID = "m-citation-rate"

_CREATED_AT = datetime(2026, 7, 1, tzinfo=UTC)
_APPROVED_AT = datetime(2026, 7, 1, 1, tzinfo=UTC)
#: On-time confirmation anchor (within the Day-2 window of `_APPROVED_AT`).
_CONFIRMED_AT_ON_TIME = datetime(2026, 7, 1, 2, tzinfo=UTC)
_SERVER_RECEIVED_AT_ON_TIME = datetime(2026, 7, 1, 2, 0, 5, tzinfo=UTC)
_ASSET_HASH_T = "sha256:" + "a" * 64
_ASSET_HASH_C = "sha256:" + "b" * 64
_CODE_VERSION_HASH = "sha256:" + "c" * 64
_WINDOW_DAYS = 7


def fixed_clock() -> str:
    return _isoformat_z(_SERVER_RECEIVED_AT_ON_TIME)


def _isoformat_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _as_sha256_ref(bundle_hash: str | None) -> str:
    """`GrsDecision.bundle_hash` (`saena_domain.measurement.grs`) is a BARE
    64-hex digest with no `sha256:` prefix, but the wire
    `experiment.outcome.observed.v1` contract's `GrsPolicy.hash` field is a
    `Sha256Ref` requiring the `sha256:` prefix (pattern
    `^sha256:[0-9a-f]{64}$`) — this normalizes the domain value onto the wire
    shape. A missing/falsy `bundle_hash` (no GRS bundle was ever evaluated)
    falls back to an explicit all-zero placeholder, never a fabricated real
    hash."""
    if not bundle_hash:
        return "sha256:" + "0" * 64
    return bundle_hash if bundle_hash.startswith("sha256:") else f"sha256:{bundle_hash}"


# ---------------------------------------------------------------------------
# Stage 1 — experiment registration ledger.
# ---------------------------------------------------------------------------


def build_registration(
    *,
    tenant_id: str = TENANT_1,
    experiment_id: str = EXPERIMENT_ID,
    run_id: str = RUN_ID,
) -> ExperimentRegistration:
    reg = ExperimentRegistration(
        experiment_id=experiment_id,
        tenant_id=tenant_id,
        run_id=run_id,
        arms=(
            ExperimentArm(arm_id="arm-base", role="baseline"),
            ExperimentArm(arm_id="arm-treat", role="treatment", asset_ref="asset-t"),
            ExperimentArm(arm_id="arm-ctrl", role="control", asset_ref="asset-c"),
        ),
        metric_definitions=(MetricDefinition(metric_id=METRIC_ID, description="citation rate"),),
        query_cluster_ref="qc-w5e2e-1",
        locale="en-US",
        browser_policy="desktop-default",
        repeat_count=3,
        asset_hash=_ASSET_HASH_T,
        code_version_hash=_CODE_VERSION_HASH,
        created_by="actor-w5e2e-author",
        approved_by="actor-w5e2e-approver",
        created_at=_CREATED_AT,
    )
    _, entry = register((), reg)
    return entry


def build_registration_view(
    registration: ExperimentRegistration, *, approved_at: datetime = _APPROVED_AT
) -> RegistrationView:
    return RegistrationView(
        experiment_id=registration.experiment_id,
        tenant_id=registration.tenant_id,
        run_id=registration.run_id,
        project="proj-w5e2e",
        site="site-w5e2e",
        registration_canonical_hash=registration.canonical_hash,
        created_at=registration.created_at,
        approved_at=approved_at,
    )


def build_submission(registration: ExperimentRegistration) -> MeasurementSubmission:
    metric = registration.metric_definitions[0]
    cell = MeasurementCell(
        locale=registration.locale,
        browser_policy=registration.browser_policy,
        query_cluster_ref=registration.query_cluster_ref,
        repeat_count=registration.repeat_count,
    )
    observations = (
        Observation(observation_id="obs-base-1", arm_id="arm-base", cell=cell),
        Observation(
            observation_id="obs-treat-1", arm_id="arm-treat", cell=cell, asset_hash=_ASSET_HASH_T
        ),
        Observation(
            observation_id="obs-ctrl-1", arm_id="arm-ctrl", cell=cell, asset_hash=_ASSET_HASH_T
        ),
    )
    return MeasurementSubmission(
        experiment_id=registration.experiment_id,
        tenant_id=registration.tenant_id,
        anchored_hash=registration.canonical_hash,
        content_fingerprint=registration.content_fingerprint,
        metrics=(
            MeasurementMetricInput(
                metric_id=metric.metric_id,
                metric_hash=compute_metric_fingerprint(metric),
                weight=1.0,
            ),
        ),
        observations=observations,
    )


def build_weights_policy(registration: ExperimentRegistration) -> WeightsPolicy:
    return WeightsPolicy.enforce({registration.metric_definitions[0].metric_id: 1.0})


# ---------------------------------------------------------------------------
# Stage 2 — deployment.confirmed.v1-shaped confirmation.
# ---------------------------------------------------------------------------


class AlwaysTrustVerifier:
    """A `TrustVerifier` double that always accepts — H5 mechanism only, never
    a production confirmer identity/key (wave5-plan.md H5: production values
    BLOCKED)."""

    def verify(self, confirmation: DeploymentConfirmation) -> bool:
        return True


def build_deployment_confirmation(
    registration: ExperimentRegistration,
    registration_view: RegistrationView,
    *,
    idempotency_key: str = "w5e2e:deploy:0001",
    confirmed_at: datetime = _CONFIRMED_AT_ON_TIME,
) -> DeploymentConfirmation:
    return DeploymentConfirmation(
        experiment_id=registration.experiment_id,
        tenant_id=registration.tenant_id,
        run_id=registration.run_id,
        project=registration_view.project,
        site=registration_view.site,
        registration_canonical_hash=registration.canonical_hash,
        deployment_target="prod-cluster-w5e2e",
        deployed_commit_sha="a" * 40,
        confirmed_at=confirmed_at,
        idempotency_key=idempotency_key,
        confirmer_identity="confirmer-w5e2e-ci-bot",
        confirmer_signature="sig-w5e2e-0001",
    )


def accept_confirmation(
    confirmation: DeploymentConfirmation,
    registration_view: RegistrationView,
    *,
    server_received_at: datetime,
    trust_verifier: TrustVerifier | None = None,
    prior_confirmations: dict[str, Any] | None = None,
) -> Any:
    """Runs the REAL `validate_confirmation` (w5-03) — never hand-builds an
    `Accepted`."""
    return validate_confirmation(
        confirmation,
        registration_view,
        server_received_at,
        trust_verifier if trust_verifier is not None else AlwaysTrustVerifier(),
        prior_confirmations or {},
    )


# ---------------------------------------------------------------------------
# Stage 3 — DiD signal series (real vs. fraud vs. insufficient fixtures).
# ---------------------------------------------------------------------------


def _cell(
    values: tuple[float, ...], *, start: datetime, step: timedelta = timedelta(hours=1)
) -> CellObservation:
    timestamps = tuple(start + step * i for i in range(len(values)))
    observation_ids = tuple(f"obs-{start.isoformat()}-{i}" for i in range(len(values)))
    return CellObservation(
        repeat_values=values, timestamps=timestamps, observation_ids=observation_ids
    )


def qualifying_signal(
    layer: str, evidence_basis_id: str, *, window_anchor: datetime
) -> SignalSeries:
    """A signal whose net-of-control lift is clearly positive (qualifies) —
    treatment moves 10->20, control barely moves 10->11."""
    pre = window_anchor - timedelta(days=1)
    post = window_anchor + timedelta(days=1)
    return SignalSeries(
        layer=layer,
        metric_id=METRIC_ID,
        evidence_basis_id=evidence_basis_id,
        baseline_treatment=_cell((10.0, 10.0, 10.0), start=pre),
        post_treatment=_cell((20.0, 20.0, 20.0), start=post),
        baseline_control=_cell((10.0, 10.0, 10.0), start=pre),
        post_control=_cell((11.0, 11.0, 11.0), start=post),
    )


def fraud_signal(layer: str, evidence_basis_id: str, *, window_anchor: datetime) -> SignalSeries:
    """k3s §10 F-9 fraud fixture: raw grows in BOTH arms equally -> net-of-
    control lift == 0 -> never PASS."""
    pre = window_anchor - timedelta(days=1)
    post = window_anchor + timedelta(days=1)
    return SignalSeries(
        layer=layer,
        metric_id=METRIC_ID,
        evidence_basis_id=evidence_basis_id,
        baseline_treatment=_cell((10.0, 10.0, 10.0), start=pre),
        post_treatment=_cell((20.0, 20.0, 20.0), start=post),
        baseline_control=_cell((10.0, 10.0, 10.0), start=pre),
        post_control=_cell((20.0, 20.0, 20.0), start=post),
    )


def observation_evidence_metadata(
    signals: tuple[SignalSeries, ...], anchor: datetime
) -> dict[str, tuple[tuple[str, EvidenceMetadata], ...]]:
    baseline: list[tuple[str, EvidenceMetadata]] = []
    treatment: list[tuple[str, EvidenceMetadata]] = []
    control: list[tuple[str, EvidenceMetadata]] = []
    for signal in signals:
        meta = EvidenceMetadata(
            timestamp=anchor.isoformat(),
            client_version=_CODE_VERSION_HASH,
            asset_hash=_ASSET_HASH_T,
            citation_present=True,
            citation="https://example.test/w5e2e-citation",
        )
        baseline.append((signal.evidence_basis_id, meta))
        treatment.append((signal.evidence_basis_id, meta))
        control.append((signal.evidence_basis_id, meta))
    return {"baseline": tuple(baseline), "treatment": tuple(treatment), "control": tuple(control)}


# ---------------------------------------------------------------------------
# Stage 4 — policies (weights / DiD / B-gate / clock / GRS / trust).
# ---------------------------------------------------------------------------


def make_did_policy() -> DiDPolicy:
    return DiDPolicy(min_repeats=3, effect_threshold=0.5, provenance="test_fixture")


def make_gate_policy() -> GatePolicy:
    return GatePolicy(
        version="0.0.0",
        hash="sha256:" + "d" * 64,
        provenance=GatePolicyProvenance.TEST_FIXTURE,
    )


def make_clock_policy() -> ClockPolicy:
    return ClockPolicy(window_days=_WINDOW_DAYS, max_deploy_delay_days=2)


def make_grs_bundle_eligible() -> GrsPolicyBundle:
    return make_test_fixture_policy(
        {"min_grs": 0, "min_independent_layers": 2, "max_open_incidents": 100}
    )


def make_grs_bundle_deny() -> GrsPolicyBundle:
    return make_test_fixture_policy(
        {"min_grs": 999, "min_independent_layers": 2, "max_open_incidents": 0}
    )


def make_policies(
    registration: ExperimentRegistration,
    *,
    grs_bundle: str | GrsPolicyBundle | None = "eligible",
    trust_verifier: TrustVerifier | None | Any = ...,
) -> MeasurementPolicies:
    resolved_grs: GrsPolicyBundle | None
    if grs_bundle == "eligible":
        resolved_grs = make_grs_bundle_eligible()
    elif grs_bundle == "deny":
        resolved_grs = make_grs_bundle_deny()
    elif grs_bundle == "missing" or grs_bundle is None:
        resolved_grs = None
    else:
        resolved_grs = grs_bundle  # type: ignore[assignment]
    resolved_trust = AlwaysTrustVerifier() if trust_verifier is ... else trust_verifier
    return MeasurementPolicies(
        weights=build_weights_policy(registration),
        did_policy=make_did_policy(),
        gate_policy=make_gate_policy(),
        clock_policy=make_clock_policy(),
        grs_bundle=resolved_grs,
        trust_verifier=resolved_trust,
    )


def make_in_memory_ports() -> MeasurementPorts:
    return MeasurementPorts(
        confirmation_store=InMemoryConfirmationStore(),
        window_store=InMemoryMeasurementWindowStore(),
        decision_store=InMemoryOutcomeDecisionStore(),
        evidence_store=InMemoryEvidenceBundleStore(),
    )


# ---------------------------------------------------------------------------
# Whole-run composition — builds a full `MeasurementInputs` for one scenario.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MeasurementScenario:
    """Every intermediate artifact of one composed measurement run, so a
    caller can assert on each stage individually (never just the final
    outcome). `did_signals` is retained verbatim (not re-derived later) so
    downstream publishing/projection steps reuse the SAME signal objects
    `run_measurement` itself computed DiD over."""

    registration: ExperimentRegistration
    registration_view: RegistrationView
    confirmation: DeploymentConfirmation
    accepted_verdict: Any
    inputs: MeasurementInputs
    window_anchor: datetime
    window_end: datetime


def _build_scenario(
    *,
    tenant_id: str,
    run_id: str,
    experiment_id: str,
    idempotency_key: str,
    signals: tuple[SignalSeries, ...],
    num_qualifying_layers: int,
) -> MeasurementScenario:
    registration = build_registration(
        tenant_id=tenant_id, experiment_id=experiment_id, run_id=run_id
    )
    registration_view = build_registration_view(registration)
    submission = build_submission(registration)
    confirmation = build_deployment_confirmation(
        registration, registration_view, idempotency_key=idempotency_key
    )
    verdict = accept_confirmation(
        confirmation, registration_view, server_received_at=_SERVER_RECEIVED_AT_ON_TIME
    )

    window_anchor = _SERVER_RECEIVED_AT_ON_TIME
    window_end = window_anchor + timedelta(days=_WINDOW_DAYS)
    evidence_meta = observation_evidence_metadata(signals, window_anchor)
    evaluation_at = window_end + timedelta(hours=1)

    inputs = MeasurementInputs(
        tenant_id=tenant_id,
        run_id=run_id,
        experiment_id=experiment_id,
        registration=registration,
        registration_view=registration_view,
        submission=submission,
        signals=signals,
        deployment_confirmation=confirmation,
        server_received_at=_SERVER_RECEIVED_AT_ON_TIME,
        evaluation_at=evaluation_at,
        prior_confirmations={},
        grs_inputs={"grs": 100, "independent_layers": num_qualifying_layers, "open_incidents": 0},
        baseline_evidence=evidence_meta["baseline"],
        treatment_evidence=evidence_meta["treatment"],
        control_evidence=evidence_meta["control"],
    )
    return MeasurementScenario(
        registration=registration,
        registration_view=registration_view,
        confirmation=confirmation,
        accepted_verdict=verdict,
        inputs=inputs,
        window_anchor=window_anchor,
        window_end=window_end,
    )


def build_pass_scenario(
    *,
    tenant_id: str = TENANT_1,
    run_id: str = RUN_ID,
    experiment_id: str = EXPERIMENT_ID,
    idempotency_key: str = "w5e2e:deploy:0001",
    num_qualifying_layers: int = 2,
) -> MeasurementScenario:
    """The full happy-path scenario: on-time confirmation + N qualifying
    layers, ready to run through `run_measurement` for a B-gate PASS."""
    layers = ["discovery", "citation", "prominence", "referral"][: max(num_qualifying_layers, 1)]
    signals = tuple(
        qualifying_signal(layer, f"basis-{layer}", window_anchor=_SERVER_RECEIVED_AT_ON_TIME)
        for layer in layers
    )
    return _build_scenario(
        tenant_id=tenant_id,
        run_id=run_id,
        experiment_id=experiment_id,
        idempotency_key=idempotency_key,
        signals=signals,
        num_qualifying_layers=num_qualifying_layers,
    )


def build_fraud_scenario(
    *, tenant_id: str = TENANT_1, idempotency_key: str = "w5e2e:deploy:fraud"
) -> MeasurementScenario:
    """Same on-time confirmation + 2-layer submission as `build_pass_scenario`,
    but with fraud (raw-up-both-arms) DiD signals -> B-gate never PASS."""
    layers = ["discovery", "citation"]
    signals = tuple(
        fraud_signal(layer, f"basis-{layer}", window_anchor=_SERVER_RECEIVED_AT_ON_TIME)
        for layer in layers
    )
    return _build_scenario(
        tenant_id=tenant_id,
        run_id=RUN_ID,
        experiment_id=EXPERIMENT_ID,
        idempotency_key=idempotency_key,
        signals=signals,
        num_qualifying_layers=2,
    )


def build_late_deployment_scenario(
    *, tenant_id: str = TENANT_1, idempotency_key: str = "w5e2e:deploy:late"
) -> MeasurementScenario:
    """Deployment confirmed 5 days after approval — past the Day-2 rule
    (Algorithm §7.3:483). The 7-day clock never starts ->
    UNDETERMINED(deployment_late)."""
    registration = build_registration(tenant_id=tenant_id)
    registration_view = build_registration_view(registration)
    submission = build_submission(registration)
    late_confirmed_at = registration_view.approved_at + timedelta(days=5)
    server_received_at = late_confirmed_at + timedelta(seconds=5)
    confirmation = build_deployment_confirmation(
        registration,
        registration_view,
        idempotency_key=idempotency_key,
        confirmed_at=late_confirmed_at,
    )
    verdict = accept_confirmation(
        confirmation, registration_view, server_received_at=server_received_at
    )
    inputs = MeasurementInputs(
        tenant_id=tenant_id,
        run_id=RUN_ID,
        experiment_id=EXPERIMENT_ID,
        registration=registration,
        registration_view=registration_view,
        submission=submission,
        signals=(),
        deployment_confirmation=confirmation,
        server_received_at=server_received_at,
        evaluation_at=server_received_at + timedelta(days=8),
        prior_confirmations={},
        grs_inputs={"grs": 100, "independent_layers": 2, "open_incidents": 0},
    )
    return MeasurementScenario(
        registration=registration,
        registration_view=registration_view,
        confirmation=confirmation,
        accepted_verdict=verdict,
        inputs=inputs,
        window_anchor=server_received_at,
        window_end=server_received_at,
    )


def run_pass_pipeline(
    ports: MeasurementPorts,
    *,
    tenant_id: str = TENANT_1,
    idempotency_key: str = "w5e2e:deploy:0001",
) -> tuple[ExperimentOutcome, MeasurementScenario]:
    scenario = build_pass_scenario(tenant_id=tenant_id, idempotency_key=idempotency_key)
    policies = make_policies(scenario.registration, grs_bundle="eligible")
    outcome = run_measurement(scenario.inputs, ports, policies)
    return outcome, scenario


# ---------------------------------------------------------------------------
# Stage 5 — OutcomePublisher (experiment.outcome.observed.v1 wire assembly).
# ---------------------------------------------------------------------------


class _StaticManifestLookup:
    def __init__(self, manifest: EvidenceBundleManifest | None) -> None:
        self._manifest = manifest

    def lookup(self, tenant_id: str, manifest_hash: str) -> EvidenceBundleManifest | None:
        if self._manifest is None or self._manifest.manifest_hash != manifest_hash:
            return None
        return self._manifest


def fetch_manifest(
    outcome: ExperimentOutcome, scenario: MeasurementScenario, evidence_store: EvidenceBundleStore
) -> EvidenceBundleManifest:
    stored = evidence_store.get(scenario.inputs.tenant_id, outcome.evidence_bundle_ref)
    return EvidenceBundleManifest(**dict(stored.manifest))


def publish_outcome_event(
    outcome: ExperimentOutcome,
    scenario: MeasurementScenario,
    evidence_store: EvidenceBundleStore,
) -> dict[str, Any]:
    """Runs the REAL `OutcomePublisher` (w5-12) over a REAL sealed manifest
    fetched back from `evidence_store` — never hand-builds the wire payload.
    Re-derives the SAME `DiDResult` the pipeline itself computed by re-running
    `compute_did` over `scenario.inputs.signals` (pure + deterministic — an
    identical recomputation, never a divergent one)."""
    assert outcome.b_gate_decision is not None
    assert outcome.grs_decision is not None
    assert outcome.evidence_bundle_ref is not None

    manifest = fetch_manifest(outcome, scenario, evidence_store)
    manifest_lookup = _StaticManifestLookup(manifest)
    publisher = OutcomePublisher(manifest_lookup=manifest_lookup)

    did_result = compute_did(
        scenario.inputs.signals,
        make_did_policy(),
        window_start=None,
        window_end=scenario.window_end,
    )
    grs = outcome.grs_decision

    return publisher.publish(
        tenant_id=scenario.inputs.tenant_id,
        engine_id=ENGINE_ID,
        experiment_id=scenario.inputs.experiment_id,
        registration_canonical_hash=scenario.registration.canonical_hash,
        deployment_confirmation_ref=scenario.confirmation.idempotency_key,
        window=WirePayloadWindow(
            started_at=_isoformat_z(scenario.window_anchor),  # type: ignore[arg-type]
            ended_at=_isoformat_z(scenario.window_end),  # type: ignore[arg-type]
            clock_anchor="deployment_confirmed",
        ),
        did_result=did_result,
        decision=outcome.b_gate_decision,
        manifest_hash=outcome.evidence_bundle_ref,
        artifact_ref=f"evidence://{scenario.inputs.tenant_id}/{outcome.evidence_bundle_ref}",
        grs_policy=WireGrsPolicy(
            version=grs.policy_version or "0.0.0",
            hash=_as_sha256_ref(grs.bundle_hash),  # type: ignore[arg-type]
            provenance=grs.provenance.value if grs.provenance is not None else "test_fixture",  # type: ignore[arg-type]
        ),
    )


# ---------------------------------------------------------------------------
# Stage 6 — strategy-skill-bank intake (B-verified-only, fail-closed).
# ---------------------------------------------------------------------------


def evaluate_intake(
    outcome: ExperimentOutcome,
    scenario: MeasurementScenario,
    evidence_store: EvidenceBundleStore,
    *,
    provenance: SourceOutcomeProvenance = SourceOutcomeProvenance.TEST_FIXTURE,
) -> IntakeDecision:
    """Runs the REAL `IntakeGuard` (w5-16) over the REAL sealed manifest this
    run produced.

    `b_verdict` is derived from `outcome.status` (the PIPELINE's fully-forced
    overall verdict — `saena_experiment_attribution.pipeline.outcome.
    OutcomeStatus`), NEVER from `outcome.b_gate_decision.verdict` alone: the
    B-gate's own signal-level verdict can legitimately still read PASS even
    when a pipeline-level fail-closed forcer (GRS non-eligibility, a binding
    reject, or a window failure — see `orchestrator.py::_final_status`)
    demoted the overall outcome to UNDETERMINED. Feeding the B-gate's raw
    verdict straight into intake would let a GRS-missing (or
    binding/window-failed) run slip past this fail-closed boundary as an
    admitted candidate — exactly the outcome-field-gap class of bug the real
    composed E2E lane (c5-01/w5-19) exists to catch."""
    from saena_domain.measurement.b_gate import BVerdict

    manifest: EvidenceBundleManifest | None = None
    if outcome.evidence_bundle_ref is not None:
        manifest = fetch_manifest(outcome, scenario, evidence_store)

    # `OutcomeStatus` is a documented 1:1 mirror of `BVerdict` (outcome.py
    # module docstring: "a 1:1 mirror of BVerdict, nothing more") — the
    # values are guaranteed identical, so this is a pure re-tag, never a
    # translation that could itself diverge.
    b_verdict = BVerdict(outcome.status.value)

    guard = IntakeGuard()
    candidate = IntakeCandidate(
        card_candidate_ref=f"card-{scenario.inputs.experiment_id}",
        evidence_bundle_manifest_hash=outcome.evidence_bundle_ref or ("sha256:" + "0" * 64),
        source_outcome=SourceOutcomeAssertion(
            b_verdict=b_verdict,
            provenance=provenance,
            manifest=manifest,
        ),
    )
    return guard.evaluate(candidate)


# ---------------------------------------------------------------------------
# Stage 7 — ClickHouse `measurement_outcome` row projection.
# ---------------------------------------------------------------------------


def measurement_outcome_row_from_outcome(
    outcome: ExperimentOutcome,
    scenario: MeasurementScenario,
    *,
    row_id: str,
) -> Any:
    """Projects a real `ExperimentOutcome` into a real `MeasurementOutcomeRow`
    (w5-11) — straight field mapping, never a re-derivation of the verdict."""
    from saena_analytics_clickhouse.rows import MeasurementOutcomeRow

    decision = outcome.b_gate_decision
    grs = outcome.grs_decision
    layer = (
        outcome.qualifying_layers[0]
        if outcome.qualifying_layers
        else (outcome.raw_view[0] if outcome.raw_view else "discovery")
    )
    return MeasurementOutcomeRow(
        tenant_id=scenario.inputs.tenant_id,
        id=row_id,
        idempotency_key=(
            f"{scenario.inputs.tenant_id}:{scenario.inputs.run_id}:{outcome.evidence_bundle_ref}"
        ),
        occurred_at=outcome.computed_at,
        experiment_id=scenario.inputs.experiment_id,
        registration_canonical_hash=scenario.registration.canonical_hash,
        window_started_at=scenario.window_anchor,
        window_ended_at=scenario.window_end,
        b_verdict=outcome.status.value,
        reason_codes=tuple(c.value for c in outcome.reason_codes),
        outcome_layer=layer,
        sample_count_treatment=3,
        sample_count_control=3,
        insufficient_data=outcome.status is OutcomeStatus.UNDETERMINED,
        evidence_bundle_manifest_hash=outcome.evidence_bundle_ref or ("sha256:" + "0" * 64),
        grs_policy_version=(
            grs.policy_version if grs is not None and grs.policy_version else "0.0.0"
        ),
        grs_policy_hash=(
            grs.bundle_hash if grs is not None and grs.bundle_hash else "sha256:" + "0" * 64
        ),
        grs_policy_provenance=(
            grs.provenance.value
            if grs is not None and grs.provenance is not None
            else "test_fixture"
        ),
        evidence_basis_id=(
            decision.qualifying_layers[0].value if decision and decision.qualifying_layers else None
        ),
        net_of_control_lift=None,
        raw_lift=None,
    )


__all__ = [
    "ENGINE_ID",
    "EXPERIMENT_ID",
    "METRIC_ID",
    "RUN_ID",
    "TENANT_1",
    "TENANT_2",
    "AlwaysTrustVerifier",
    "MeasurementScenario",
    "accept_confirmation",
    "build_deployment_confirmation",
    "build_fraud_scenario",
    "build_late_deployment_scenario",
    "build_pass_scenario",
    "build_registration",
    "build_registration_view",
    "build_submission",
    "build_weights_policy",
    "evaluate_intake",
    "fetch_manifest",
    "fixed_clock",
    "fraud_signal",
    "make_clock_policy",
    "make_did_policy",
    "make_gate_policy",
    "make_grs_bundle_deny",
    "make_grs_bundle_eligible",
    "make_in_memory_ports",
    "make_policies",
    "measurement_outcome_row_from_outcome",
    "observation_evidence_metadata",
    "publish_outcome_event",
    "qualifying_signal",
    "run_pass_pipeline",
]

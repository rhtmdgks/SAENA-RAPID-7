"""Shared test factories for `tests/unit/svc_experiment_attribution_pipeline`.

Builds a self-consistent "happy path" experiment registration + binding
submission + deployment confirmation + DiD signal set + policies + ports, so
individual test modules only need to override the ONE thing they are
exercising (mirrors the discriminating-fixture discipline wave5-plan.md's
directive §8 requires: reproducers/discriminating fixtures BEFORE
implementation per core unit).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from saena_domain.experiment.ledger import register
from saena_domain.experiment.models import (
    ExperimentArm,
    ExperimentRegistration,
    MetricDefinition,
)
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
)
from saena_domain.measurement.did import CellObservation, DiDPolicy, SignalSeries
from saena_domain.measurement.grs import make_test_fixture_policy
from saena_domain.measurement.ports import (
    InMemoryConfirmationStore,
    InMemoryEvidenceBundleStore,
    InMemoryMeasurementWindowStore,
    InMemoryOutcomeDecisionStore,
)
from saena_experiment_attribution.pipeline.inputs import (
    MeasurementInputs,
    MeasurementPolicies,
    MeasurementPorts,
)

TENANT = "acme-co"
RUN_ID = "run-0001"
EXPERIMENT_ID = "exp-0001"

_CREATED_AT = datetime(2026, 7, 1, tzinfo=UTC)
_APPROVED_AT = datetime(2026, 7, 1, 1, tzinfo=UTC)
_CONFIRMED_AT = datetime(2026, 7, 1, 2, tzinfo=UTC)
_SERVER_RECEIVED_AT = datetime(2026, 7, 1, 2, 0, 5, tzinfo=UTC)
_METRIC_ID = "m1"
_ASSET_HASH_T = "sha256:" + "a" * 64
_ASSET_HASH_C = "sha256:" + "b" * 64
_CODE_VERSION_HASH = "sha256:" + "c" * 64


class AlwaysTrustVerifier:
    """A `TrustVerifier` double that always accepts — the deterministic
    happy-path confirmer trust decision (H5 mechanism only)."""

    def verify(self, confirmation: DeploymentConfirmation) -> bool:
        return True


class AlwaysRejectVerifier:
    """A `TrustVerifier` double that always rejects."""

    def verify(self, confirmation: DeploymentConfirmation) -> bool:
        return False


def make_registration(
    *,
    experiment_id: str = EXPERIMENT_ID,
    tenant_id: str = TENANT,
    run_id: str = RUN_ID,
    matched_cluster: bool = False,
    repeat_count: int = 3,
) -> ExperimentRegistration:
    if matched_cluster:
        arms = (
            ExperimentArm(arm_id="arm-base", role="baseline"),
            ExperimentArm(arm_id="arm-treat", role="matched_cluster", query_cluster_ref="qc-treat"),
            ExperimentArm(arm_id="arm-ctrl", role="matched_cluster", query_cluster_ref="qc-ctrl"),
        )
    else:
        arms = (
            ExperimentArm(arm_id="arm-base", role="baseline"),
            ExperimentArm(arm_id="arm-treat", role="treatment", asset_ref="asset-t"),
            ExperimentArm(arm_id="arm-ctrl", role="control", asset_ref="asset-c"),
        )
    reg = ExperimentRegistration(
        experiment_id=experiment_id,
        tenant_id=tenant_id,
        run_id=run_id,
        arms=arms,
        metric_definitions=(MetricDefinition(metric_id=_METRIC_ID, description="citation rate"),),
        query_cluster_ref="qc-1",
        locale="en-US",
        browser_policy="default",
        repeat_count=repeat_count,
        asset_hash=_ASSET_HASH_T,
        code_version_hash=_CODE_VERSION_HASH,
        created_by="user-1",
        approved_by="user-2",
        created_at=_CREATED_AT,
    )
    _, entry = register((), reg)
    return entry


def make_registration_view(registration: ExperimentRegistration) -> RegistrationView:
    return RegistrationView(
        experiment_id=registration.experiment_id,
        tenant_id=registration.tenant_id,
        run_id=registration.run_id,
        project="proj-1",
        site="site-1",
        registration_canonical_hash=registration.canonical_hash,
        created_at=registration.created_at,
        approved_at=_APPROVED_AT,
    )


def make_submission(
    registration: ExperimentRegistration, *, observations: tuple[Observation, ...] | None = None
) -> MeasurementSubmission:
    metric = registration.metric_definitions[0]
    cell = MeasurementCell(
        locale=registration.locale,
        browser_policy=registration.browser_policy,
        query_cluster_ref=registration.query_cluster_ref,
        repeat_count=registration.repeat_count,
    )
    if observations is None:
        observations = (
            Observation(
                observation_id="obs-base-1",
                arm_id="arm-base",
                cell=cell,
            ),
            Observation(
                observation_id="obs-treat-1",
                arm_id="arm-treat",
                cell=cell,
                asset_hash=_ASSET_HASH_T,
            ),
            Observation(
                observation_id="obs-ctrl-1",
                arm_id="arm-ctrl",
                cell=cell,
                asset_hash=_ASSET_HASH_T,
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


def make_weights_policy(registration: ExperimentRegistration) -> WeightsPolicy:
    return WeightsPolicy.enforce({registration.metric_definitions[0].metric_id: 1.0})


def make_deployment_confirmation(
    registration: ExperimentRegistration,
    registration_view: RegistrationView,
    *,
    idempotency_key: str = "acme-co:run-0001:deploy",
    confirmed_at: datetime = _CONFIRMED_AT,
) -> DeploymentConfirmation:
    return DeploymentConfirmation(
        experiment_id=registration.experiment_id,
        tenant_id=registration.tenant_id,
        run_id=registration.run_id,
        project=registration_view.project,
        site=registration_view.site,
        registration_canonical_hash=registration.canonical_hash,
        deployment_target="prod-cluster-1",
        deployed_commit_sha="a" * 40,
        confirmed_at=confirmed_at,
        idempotency_key=idempotency_key,
        confirmer_identity="confirmer-1",
        confirmer_signature="sig-1",
    )


def _cell(
    values: tuple[float, ...], *, start: datetime, step: timedelta = timedelta(hours=1)
) -> CellObservation:
    timestamps = tuple(start + step * i for i in range(len(values)))
    observation_ids = tuple(f"obs-{start.isoformat()}-{i}" for i in range(len(values)))
    return CellObservation(
        repeat_values=values, timestamps=timestamps, observation_ids=observation_ids
    )


def make_qualifying_signal(
    layer: str, evidence_basis_id: str, *, window_anchor: datetime
) -> SignalSeries:
    """A signal whose net-of-control lift is clearly positive (qualifies)."""
    pre = window_anchor - timedelta(days=1)
    post = window_anchor + timedelta(days=1)
    return SignalSeries(
        layer=layer,
        metric_id=_METRIC_ID,
        evidence_basis_id=evidence_basis_id,
        baseline_treatment=_cell((10.0, 10.0, 10.0), start=pre),
        post_treatment=_cell((20.0, 20.0, 20.0), start=post),
        baseline_control=_cell((10.0, 10.0, 10.0), start=pre),
        post_control=_cell((11.0, 11.0, 11.0), start=post),
    )


def make_fraud_signal(
    layer: str, evidence_basis_id: str, *, window_anchor: datetime
) -> SignalSeries:
    """F-9 fraud fixture: raw grows in both arms equally -> net lift == 0."""
    pre = window_anchor - timedelta(days=1)
    post = window_anchor + timedelta(days=1)
    return SignalSeries(
        layer=layer,
        metric_id=_METRIC_ID,
        evidence_basis_id=evidence_basis_id,
        baseline_treatment=_cell((10.0, 10.0, 10.0), start=pre),
        post_treatment=_cell((20.0, 20.0, 20.0), start=post),
        baseline_control=_cell((10.0, 10.0, 10.0), start=pre),
        post_control=_cell((20.0, 20.0, 20.0), start=post),
    )


def make_did_policy(*, min_repeats: int = 3, effect_threshold: float = 0.5) -> DiDPolicy:
    return DiDPolicy(
        min_repeats=min_repeats,
        effect_threshold=effect_threshold,
        provenance="test_fixture",
    )


def make_gate_policy() -> GatePolicy:
    return GatePolicy(
        version="0.0.0", hash="sha256:" + "d" * 64, provenance=GatePolicyProvenance.TEST_FIXTURE
    )


def make_clock_policy() -> ClockPolicy:
    return ClockPolicy(window_days=7, max_deploy_delay_days=2)


def make_grs_bundle_eligible() -> Any:
    return make_test_fixture_policy(
        {"min_grs": 0, "min_independent_layers": 2, "max_open_incidents": 100}
    )


def make_grs_bundle_deny() -> Any:
    return make_test_fixture_policy(
        {"min_grs": 999, "min_independent_layers": 2, "max_open_incidents": 0}
    )


def make_ports() -> MeasurementPorts:
    return MeasurementPorts(
        confirmation_store=InMemoryConfirmationStore(),
        window_store=InMemoryMeasurementWindowStore(),
        decision_store=InMemoryOutcomeDecisionStore(),
        evidence_store=InMemoryEvidenceBundleStore(),
    )


_UNSET = object()


def make_policies(
    registration: ExperimentRegistration,
    *,
    trust_verifier: Any = _UNSET,
    grs_bundle: Any | None = "eligible",
    did_policy: DiDPolicy | None = None,
    gate_policy: GatePolicy | None = None,
    clock_policy: ClockPolicy | None = None,
) -> MeasurementPolicies:
    """Build a `MeasurementPolicies`. `trust_verifier` defaults to an
    always-accept double when the keyword is OMITTED entirely; passing
    `trust_verifier=None` explicitly means "no verifier injected" (the
    fail-closed `UNTRUSTED_CONFIRMER` case) — the two are deliberately
    distinguished via a sentinel default, not `is not None`, so a test can
    assert the no-verifier fail-closed path without fighting a truthy
    default."""
    if grs_bundle == "eligible":
        grs_bundle = make_grs_bundle_eligible()
    elif grs_bundle == "deny":
        grs_bundle = make_grs_bundle_deny()
    elif grs_bundle == "missing":
        grs_bundle = None
    resolved_trust_verifier = AlwaysTrustVerifier() if trust_verifier is _UNSET else trust_verifier
    return MeasurementPolicies(
        weights=make_weights_policy(registration),
        did_policy=did_policy or make_did_policy(),
        gate_policy=gate_policy or make_gate_policy(),
        clock_policy=clock_policy or make_clock_policy(),
        grs_bundle=grs_bundle,
        trust_verifier=resolved_trust_verifier,
    )


def make_happy_path_inputs(
    *,
    num_qualifying_layers: int = 2,
    evaluation_at: datetime | None = None,
) -> tuple[MeasurementInputs, ExperimentRegistration]:
    registration = make_registration()
    registration_view = make_registration_view(registration)
    submission = make_submission(registration)
    confirmation = make_deployment_confirmation(registration, registration_view)

    window_anchor = _SERVER_RECEIVED_AT
    layers = ["discovery", "citation", "prominence", "referral"][: max(num_qualifying_layers, 1)]
    signals = tuple(
        make_qualifying_signal(layer, f"basis-{layer}", window_anchor=window_anchor)
        for layer in layers
    )
    if evaluation_at is None:
        window_end = window_anchor + timedelta(days=7)
        evaluation_at = window_end + timedelta(hours=1)

    baseline_meta = _observation_metadata(signals, window_anchor)

    inputs = MeasurementInputs(
        tenant_id=registration.tenant_id,
        run_id=registration.run_id,
        experiment_id=registration.experiment_id,
        registration=registration,
        registration_view=registration_view,
        submission=submission,
        signals=signals,
        deployment_confirmation=confirmation,
        server_received_at=_SERVER_RECEIVED_AT,
        evaluation_at=evaluation_at,
        prior_confirmations={},
        grs_inputs={"grs": 100, "independent_layers": num_qualifying_layers, "open_incidents": 0},
        baseline_evidence=baseline_meta["baseline"],
        treatment_evidence=baseline_meta["treatment"],
        control_evidence=baseline_meta["control"],
    )
    return inputs, registration


def _observation_metadata(
    signals: tuple[SignalSeries, ...], anchor: datetime
) -> dict[str, tuple[tuple[str, Any], ...]]:
    from saena_domain.measurement.evidence import EvidenceMetadata

    baseline: list[tuple[str, EvidenceMetadata]] = []
    treatment: list[tuple[str, EvidenceMetadata]] = []
    control: list[tuple[str, EvidenceMetadata]] = []
    for signal in signals:
        meta = EvidenceMetadata(
            timestamp=anchor.isoformat(),
            client_version=_CODE_VERSION_HASH,
            asset_hash=_ASSET_HASH_T,
            citation_present=True,
            citation="https://example.test/citation",
        )
        baseline.append((signal.evidence_basis_id, meta))
        treatment.append((signal.evidence_basis_id, meta))
        control.append((signal.evidence_basis_id, meta))
    return {"baseline": tuple(baseline), "treatment": tuple(treatment), "control": tuple(control)}


__all__ = [
    "TENANT",
    "RUN_ID",
    "EXPERIMENT_ID",
    "AlwaysTrustVerifier",
    "AlwaysRejectVerifier",
    "make_registration",
    "make_registration_view",
    "make_submission",
    "make_weights_policy",
    "make_deployment_confirmation",
    "make_qualifying_signal",
    "make_fraud_signal",
    "make_did_policy",
    "make_gate_policy",
    "make_clock_policy",
    "make_grs_bundle_eligible",
    "make_grs_bundle_deny",
    "make_ports",
    "make_policies",
    "make_happy_path_inputs",
]
